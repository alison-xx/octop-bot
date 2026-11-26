"""Image and video generation through Lynxce, billed to the Bot owner's Lynxce credits.

octop-harness has built-in adapters for Volcengine, DashScope and MiniMax only, and builds them
from a static API key. A Lynxce credential is per user and can rotate (the desktop sign-in's
OAuth token, a cloud tenant's personal key), so this adapter implements the harness's public
``MediaGenerationProvider`` protocol and is handed to ``build_media_generation_tools`` through
a ``MediaManager``: the tool schema, workspace storage, result envelope and chat media cards are
the harness's and Octop's existing ones.

Lynxce's gateway (``/api/v1``) is asynchronous for both kinds: ``POST /images/generations`` and
``POST /videos/generations`` return ``{id, status}``; ``GET /generations/{id}`` is polled until
``status`` is ``succeeded`` with ``data[].url`` (or ``b64_json``). A key needs the
``media:image`` / ``media:video`` scopes; an OAuth grant the ``media`` scope.

Cloud tenants use GPT Image 2.6 and MiniMax H3. Other sign-ins follow Lynxce's ordered
model catalog: the first image and the first video model in ``GET /models`` are its
defaults (Lynxce's own MCP tools pick the same way). The adapter reads that list, keeps it for a
few minutes, and falls back to fixed models only when the list cannot be read, so a new default
set in Lynxce's admin reaches every Bot without an Octop release.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command
from octop_harness.media import MediaGenerationError
from octop_harness.media.http import detect_media, response_error
from octop_harness.media.models import (
    GeneratedMedia,
    ImageGenerationRequest,
    MediaCapabilities,
    MediaJobUpdate,
    MediaSubmission,
    ProviderTask,
    RemoteArtifact,
    VideoGenerationRequest,
)
from pydantic import Field, create_model

from octop.i18n import tr
from octop.infra.auth.lynxce_cloud import LYNXCE_APP_HEADERS
from octop.infra.utils.locale import DEFAULT_LOCALE, Locale

if TYPE_CHECKING:
    from octop_harness.backends.workspace import BackendWorkspace

logger = logging.getLogger(__name__)

# Cloud tenant defaults, also used if other installations cannot read the catalog.
IMAGE_MODEL = "gpt-image-2.6-flare"
VIDEO_MODEL = "ucloud/MiniMax-H3"
# How long one read of Lynxce's defaults is used, and how soon to try again after a failed read.
DEFAULTS_TTL_SECONDS = 600.0
DEFAULTS_RETRY_SECONDS = 60.0
LYNXCE_HOSTS = frozenset({"api.lynxce.cn", "center.lynxce.cn"})
# Lynxce records the Bot behind each model or media call so usage can be broken down per Bot;
# X-Lynxce-App (LYNXCE_APP_HEADERS) marks the call as Octop Bot's, as on model gateway calls.
BOT_ID_HEADER = "X-Lynxce-Bot-Id"

_LABEL_WAIT = 30 * 60
_GENERATION_WAIT = 15 * 60
_unlabelled = ContextVar("lynxce_media_unlabelled", default=False)

_RUNNING = frozenset({"running", "queued", "pending", "submitting", "processing", "uncertain"})
_FAILED = frozenset({"failed", "timeout", "cancelled"})


@dataclass
class _MediaRun:
    call_id: str
    write: Callable[[dict[str, Any]], None]
    client: httpx.AsyncClient
    started: float = field(default_factory=time.monotonic)
    accepted: float | None = None
    ready: float | None = None
    last: tuple[str, int | None] | None = None

    def report(self, phase: str, progress: object = None) -> None:
        percent = (
            int(progress)
            if isinstance(progress, (int, float))
            and not isinstance(progress, bool)
            and 0 <= progress <= 100
            else None
        )
        if self.last == (phase, percent):
            return
        self.last = (phase, percent)
        self.write(
            {"kind": "media_progress", "call_id": self.call_id, "phase": phase, "percent": percent}
        )

    def timings(self) -> dict[str, int]:
        end = time.monotonic()
        times = {"total_ms": round((end - self.started) * 1000)}
        if self.accepted is not None:
            times["submit_ms"] = round((self.accepted - self.started) * 1000)
        if self.ready is not None:
            times["delivery_ms"] = round((end - self.ready) * 1000)
            times["ready_ms"] = round((self.ready - self.started) * 1000)
        return times


_media_run: ContextVar[_MediaRun | None] = ContextVar("lynxce_media_run", default=None)


@dataclass(frozen=True)
class LynxceMediaAuth:
    """Where to call and with what bearer, resolved for every request."""

    base_url: str
    bearer: str


AuthSource = Callable[[], Awaitable[LynxceMediaAuth]]

# (base URL, hash of the bearer) -> (valid until, {"image": model, "video": model}). The list
# depends on the account (scopes, organization), hence one entry per credential.
_defaults_cache: dict[tuple[str, str], tuple[float, dict[str, str]]] = {}


def _first_models(body: Any) -> dict[str, str]:
    """The first image and the first video model of a ``GET /models`` reply, in Lynxce's order."""
    found: dict[str, str] = {}
    rows = body.get("data") if isinstance(body, dict) else None
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict):
            continue
        model, modality = row.get("id"), row.get("modality")
        if isinstance(model, str) and model and modality in ("image", "video"):
            found.setdefault(modality, model)
    return found


def _credits_error(
    response: httpx.Response, *, provider_task_id: str | None
) -> MediaGenerationError:
    """402: the wallet is short, or the key's own daily or monthly credit cap is reached.

    Both keep Lynxce's code in ``provider_code`` so clients can offer the recharge flow; the
    model is told to say so in plain words, not to repeat the technical error.
    """
    base = response_error(response, provider_task_id=provider_task_id)
    if base.provider_code == "api_key_credit_limit_reached":
        return MediaGenerationError(
            str(base),
            code="credit_limit_reached",
            category="quota",
            remediation="raise_credit_limit",
            model_instruction=(
                "Do not retry. Tell the user, without technical details, that today's Lynxce "
                "credit limit for this Bot has been used up, and that it resets daily or can be "
                "raised in the Lynxce account centre."
            ),
            provider_code=base.provider_code,
            provider_task_id=provider_task_id,
            http_status=402,
        )
    return MediaGenerationError(
        str(base),
        code="insufficient_credits",
        category="quota",
        remediation="recharge",
        model_instruction=(
            "Do not retry. Tell the user, without technical details, that their Lynxce credits "
            "are not enough for this and that they can recharge to continue."
        ),
        provider_code=base.provider_code,
        provider_task_id=provider_task_id,
        http_status=402,
    )


def _error(response: httpx.Response, *, provider_task_id: str | None) -> MediaGenerationError:
    if response.status_code == 402:
        return _credits_error(response, provider_task_id=provider_task_id)
    error = response_error(response, provider_task_id=provider_task_id)
    if response.status_code == 403 and error.provider_code == "api_key_scope_forbidden":
        return MediaGenerationError(
            str(error),
            code="media_scope_required",
            category="authorization",
            remediation="reauthorize",
            model_instruction=(
                "Do not retry. Tell the user that their Lynxce authorization does not include "
                "image and video generation yet and that signing in to Lynxce again grants it."
            ),
            provider_code=error.provider_code,
            provider_task_id=provider_task_id,
            http_status=403,
        )
    return error


class LynxceMediaProvider:
    """``MediaGenerationProvider`` for Lynxce's asynchronous media gateway."""

    provider_id = "lynxce"
    capabilities = MediaCapabilities(
        image_references=True, video_first_frame=True, video_references=True
    )
    poll_interval_seconds = 4.0
    task_timeout_seconds = _GENERATION_WAIT + _LABEL_WAIT + 2 * poll_interval_seconds

    def __init__(
        self,
        auth: AuthSource,
        *,
        image_model: str | None = None,
        video_model: str | None = None,
        client: httpx.AsyncClient | None = None,
        bot_id: str | None = None,
    ) -> None:
        """``image_model`` / ``video_model`` pin a model; left out, Lynxce's defaults are used."""
        self._auth = auth
        self._headers = {**LYNXCE_APP_HEADERS, **({BOT_ID_HEADER: bot_id} if bot_id else {})}
        self._pinned = {"image": image_model, "video": video_model}
        self._used = {"image": image_model or IMAGE_MODEL, "video": video_model or VIDEO_MODEL}
        self._client = client

    @property
    def image_model(self) -> str:
        """The model of the latest image request (the fallback until one is made)."""
        return self._used["image"]

    @property
    def video_model(self) -> str:
        return self._used["video"]

    async def _get(self, url: str, headers: dict[str, str]) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(url, headers=headers)
        async with httpx.AsyncClient(timeout=15) as client:
            return await client.get(url, headers=headers)

    async def _lynxce_defaults(self, auth: LynxceMediaAuth) -> dict[str, str]:
        """Lynxce's current default image and video models, read at most every few minutes."""
        key = (auth.base_url, hashlib.sha256(auth.bearer.encode()).hexdigest())
        cached = _defaults_cache.get(key)
        now = time.monotonic()
        if cached is not None and cached[0] > now:
            return cached[1]
        found: dict[str, str] = {}
        try:
            response = await self._get(
                auth.base_url + "/models",
                {**self._headers, "Authorization": f"Bearer {auth.bearer}"},
            )
            if response.is_success:
                found = _first_models(response.json())
            else:
                logger.warning("Lynxce model list returned HTTP %s", response.status_code)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Lynxce model list could not be read: %s", exc)
        for kind, fallback in (("image", IMAGE_MODEL), ("video", VIDEO_MODEL)):
            if kind not in found:
                logger.warning("No Lynxce default %s model; using %s", kind, fallback)
        ttl = DEFAULTS_TTL_SECONDS if len(found) == 2 else DEFAULTS_RETRY_SECONDS
        _defaults_cache[key] = (now + ttl, found)
        return found

    async def _model(self, kind: str) -> str:
        pinned = self._pinned[kind]
        if pinned:
            return pinned
        try:
            auth = await self._auth()
        except Exception:  # noqa: BLE001 - the submit itself reports the missing sign-in
            return self._used[kind]
        fallback = IMAGE_MODEL if kind == "image" else VIDEO_MODEL
        model = (await self._lynxce_defaults(auth)).get(kind) or fallback
        self._used[kind] = model
        return model

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        provider_task_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            auth = await self._auth()
        except MediaGenerationError:
            raise
        except Exception as exc:  # noqa: BLE001 - signed out, revoked: the model says so
            raise MediaGenerationError(
                "No Lynxce account is available for image and video generation.",
                code="credential_missing",
                category="authentication",
                remediation="sign_in",
                model_instruction=(
                    "Do not retry. Tell the user to sign in to their Lynxce account again."
                ),
            ) from exc
        headers = {**self._headers, "Authorization": f"Bearer {auth.bearer}"}
        if method == "POST":
            # A retried submit must not start (and bill) a second task.
            headers["Idempotency-Key"] = uuid4().hex

        async def send(client: httpx.AsyncClient) -> httpx.Response:
            # Keep the same idempotency key and credential when a response is lost.
            url = auth.base_url + path
            try:
                reply = await client.request(method, url, json=json, headers=headers)
                if reply.status_code not in (502, 503, 504):
                    return reply
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.25)
            return await client.request(method, url, json=json, headers=headers)

        try:
            run = _media_run.get()
            pooled = self._client or (run.client if run else None)
            if pooled is not None:
                response = await send(pooled)
            else:
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await send(client)
        except httpx.HTTPError as exc:
            raise MediaGenerationError(
                "Lynxce could not be reached.",
                code="provider_unavailable",
                retryable=method == "GET",
                safe_to_resubmit=False,
                remediation="check_task_status",
                provider_task_id=provider_task_id,
            ) from exc
        if response.is_error:
            error = _error(response, provider_task_id=provider_task_id)
            if method == "POST" and (
                response.status_code >= 500
                or error.provider_code == "idempotency_request_in_progress"
            ):
                error.safe_to_resubmit = False
                error.model_instruction = (
                    "Do not start another task: the submission may already have been accepted."
                )
            raise error
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise MediaGenerationError(
                "Lynxce returned an unreadable reply.", provider_task_id=provider_task_id
            )
        return body

    def _update(self, body: dict[str, Any], task: ProviderTask) -> MediaJobUpdate:
        status = str(body.get("status") or "")
        task_id = task.task_id
        now = time.monotonic()
        run = _media_run.get()
        if status == "succeeded":
            if body.get("aigc_label_ready") is not True:
                since = float(task.metadata.setdefault("finalizing_since", str(now)))
                error = body.get("error")
                failed = isinstance(error, dict) and error.get("code") == "aigc_label_failed"
                if not failed and now - since < _LABEL_WAIT:
                    if run:
                        run.report("finalizing")
                    return MediaJobUpdate(status="running")
                from octop.infra.metrics import METRICS  # noqa: PLC0415

                METRICS.inc("media_label_unavailable_total")
                _unlabelled.set(True)
            artifacts = _artifacts(body)
            if artifacts:
                if run:
                    run.ready = now
                    run.report("delivering")
                return MediaJobUpdate(status="succeeded", artifacts=artifacts)
            raise MediaGenerationError("Lynxce returned no result.", provider_task_id=task_id)
        if status in _RUNNING:
            if run:
                run.report(
                    "queued" if status in {"pending", "queued"} else "generating",
                    body.get("progress"),
                )
            started = float(task.metadata.setdefault("started", str(now)))
            if now - started >= _GENERATION_WAIT:
                raise MediaGenerationError(
                    "Lynxce generation timed out.",
                    code="provider_timeout",
                    safe_to_resubmit=False,
                    provider_task_id=task_id,
                )
            return MediaJobUpdate(
                status="pending" if status in {"pending", "queued"} else "running"
            )
        error = body.get("error")
        message = (
            str(error.get("message") or error.get("code"))
            if isinstance(error, dict)
            else f"Lynxce generation {status or 'failed'}"
        )
        raise MediaGenerationError(
            message,
            code="provider_task_failed",
            remediation="adjust_request",
            model_instruction="Do not retry automatically. Tell the user it failed and why.",
            provider_code=str(error.get("code")) if isinstance(error, dict) else status or None,
            provider_task_id=task_id,
        )

    async def _submit(self, kind: str, path: str, payload: dict[str, Any]) -> MediaSubmission:
        body = await self._request("POST", path, json=payload)
        task_id = body.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise MediaGenerationError("Lynxce returned no task id.")
        model = str(payload["model"])
        task = ProviderTask(task_id=task_id, kind=kind, model=model)  # type: ignore[arg-type]
        run = _media_run.get()
        if run:
            run.accepted = time.monotonic()
        update = self._update(body, task)
        if update.status == "succeeded":
            return MediaSubmission(artifacts=update.artifacts)
        return MediaSubmission(task=task)

    async def submit_image(self, request: ImageGenerationRequest) -> MediaSubmission:
        payload: dict[str, Any] = {
            "model": await self._model("image"),
            "prompt": request.prompt,
            "n": request.count,
        }
        if request.size:
            field = (
                "aspect_ratio" if re.fullmatch(r"[1-9]\d?\s*:\s*[1-9]\d?", request.size) else "size"
            )
            payload[field] = request.size
        if request.reference_images:
            payload["images"] = list(request.reference_images)
        return await self._submit("image", "/images/generations", payload)

    async def submit_video(self, request: VideoGenerationRequest) -> MediaSubmission:
        if request.last_frame:
            raise MediaGenerationError(
                "An ending frame is not supported here; use a starting frame or references.",
                code="invalid_request",
                category="validation",
                safe_to_resubmit=True,
                remediation="adjust_request",
                model_instruction="Call the tool again without last_frame.",
            )
        images = [
            *([request.first_frame] if request.first_frame else []),
            *request.reference_images,
        ]
        payload: dict[str, Any] = {
            "model": await self._model("video"),
            "prompt": request.prompt,
            "duration": request.duration,
            "resolution": request.resolution,
            "aspect_ratio": request.aspect_ratio,
        }
        if images:
            payload["images"] = images
        return await self._submit("video", "/videos/generations", payload)

    async def poll(self, task: ProviderTask) -> MediaJobUpdate:
        body = await self._request(
            "GET", f"/generations/{task.task_id}", provider_task_id=task.task_id
        )
        return self._update(body, task)

    async def cancel(self, task: ProviderTask) -> None:
        """Lynxce has no cancel endpoint; an abandoned task still finishes (and bills)."""
        del task

    async def load_artifact(self, artifact: RemoteArtifact) -> GeneratedMedia:
        fallback = (
            ("video/mp4", "mp4") if artifact.media_type == "video/mp4" else ("image/png", "png")
        )
        if artifact.data is not None:
            data = artifact.data
        else:
            assert artifact.url is not None
            try:
                # Result links are signed storage URLs: no Lynxce credential goes with them.
                if self._client is not None:
                    response = await self._client.get(artifact.url, follow_redirects=True)
                else:
                    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
                        response = await client.get(artifact.url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise MediaGenerationError(
                    "The generated file could not be downloaded from Lynxce.",
                    code="download_failed",
                    retryable=True,
                    remediation="retry_download",
                    model_instruction="Do not regenerate. Tell the user the download failed.",
                ) from exc
            data = response.content
        media_type, extension = detect_media(
            data, fallback_type=fallback[0], fallback_extension=fallback[1]
        )
        return GeneratedMedia(data=data, media_type=media_type, extension=extension)


def _artifacts(body: dict[str, Any]) -> tuple[RemoteArtifact, ...]:
    kind = "video/mp4" if body.get("type") == "video" else None
    out: list[RemoteArtifact] = []
    for row in body.get("data") or ():
        if not isinstance(row, dict):
            continue
        if isinstance(row.get("b64_json"), str) and row["b64_json"]:
            out.append(RemoteArtifact(data=base64.b64decode(row["b64_json"]), media_type=kind))
        elif isinstance(row.get("url"), str) and row["url"].startswith(("https://", "http://")):
            out.append(RemoteArtifact(url=row["url"], media_type=kind))
    return tuple(out)


# octop-harness tells the model this when its own ``media_generation`` config is unset, which
# is the case whenever Lynxce makes the media (see LynxceMediaTools).
_HARNESS_NOT_CONFIGURED = (
    " Image and video generation tools are not configured in this runtime. "
    "If the user asks for generated media, state that configuration is required; "
    "do not claim that media was generated."
)
_AVAILABLE = (
    "Image and video generation are available: generate_image and generate_video, billed to "
    "the user's Lynxce credits. For requests to create or edit images, call generate_image. "
    "For 2 to 4 variations of the same prompt, use one call with the requested count. "
    "For distinct scenes use their respective prompts. For a video, call generate_video. "
    "For a request whose only deliverable is an image, a batch of variations, or one short "
    "video, submit the media tool directly. Set final_delivery=true when offered for that "
    "standalone request. Skip a separate task_plan or write_todos. "
    "The tools call Lynxce directly and save deliverables to the workspace. For generation and "
    "delivery use only these media tools; do not start a cloud computer, shell, or browser. "
    "Before submitting a video, tell the user briefly that generation may take a few minutes. "
    "Only report that a job has started after its tool has been called. "
    "Completed tools attach the files to this conversation. Briefly report the actual number "
    "returned, then finish. Only list or reopen those files if the user asked to inspect them. "
    "Do not send the same files again, paste workspace paths, or resubmit a partial batch "
    "automatically."
)


def _final_media_reply(request: ModelRequest[Any], locale: Locale) -> ModelResponse[Any] | None:
    # Only a whole, successful tool batch explicitly designated for final delivery closes
    # tool selection. A new user message or a compound task retains the normal toolset.
    messages = request.messages
    if not messages or not isinstance(messages[-1], ToolMessage):
        return None
    count = 0
    for message in reversed(messages):
        if not isinstance(message, ToolMessage):
            break
        if message.name not in {"generate_image", "generate_video"} or not isinstance(
            message.content, str
        ):
            return None
        try:
            result = json.loads(message.content)
        except ValueError:
            return None
        if not isinstance(result, dict) or result.get("final_delivery") is not True:
            return None
        files = result.get("images" if message.name == "generate_image" else "videos")
        if not isinstance(files, list) or not files:
            return None
        count += len(files)
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, ToolMessage) and message.name == "task_plan":
            return None
    return ModelResponse(
        result=[AIMessage(content=tr("octop_bot.media_delivered", locale, count=count))]
    )


def _with_media_prompt(request: ModelRequest[Any]) -> ModelRequest[Any]:
    blocks: list[Any] = []
    for block in request.system_message.content_blocks if request.system_message else []:
        text = block.get("text") if block.get("type") == "text" else None
        if isinstance(text, str) and _HARNESS_NOT_CONFIGURED in text:
            blocks.append({**block, "text": text.replace(_HARNESS_NOT_CONFIGURED, "")})
        else:
            blocks.append(block)
    blocks.append({"type": "text", "text": ("\n\n" if blocks else "") + _AVAILABLE})
    return request.override(system_message=SystemMessage(content_blocks=blocks))


class LynxceMediaTools(AgentMiddleware[Any, Any]):
    """Adds the Lynxce ``generate_image`` / ``generate_video`` tools and says so in the prompt.

    The harness's built-in media tools are configured through ``media_generation``, which only
    takes its three vendors and a static key; with it unset, the harness's prompt says media
    generation is not configured. This middleware replaces that sentence.
    """

    def __init__(self, tools: list[BaseTool], *, locale: Locale = DEFAULT_LOCALE) -> None:
        self.tools = tools
        self.locale = locale

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        call = request.tool_call
        if call.get("name") not in {"generate_image", "generate_video"}:
            return await handler(request)
        async with httpx.AsyncClient(timeout=60) as client:
            run = _MediaRun(str(call.get("id") or ""), request.runtime.stream_writer, client)
            token = _media_run.set(run)
            try:
                run.report("submitting")
                return await handler(request)
            finally:
                _media_run.reset(token)

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        return _final_media_reply(request, self.locale) or handler(_with_media_prompt(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return _final_media_reply(request, self.locale) or await handler(
            _with_media_prompt(request)
        )


def _with_label_notice(
    generate: Callable[..., Awaitable[dict[str, object]]],
) -> Callable[..., Awaitable[dict[str, object]]]:
    @wraps(generate)
    async def deliver(*args: Any, **kwargs: Any) -> dict[str, object]:
        token = _unlabelled.set(False)
        try:
            final_delivery = kwargs.pop("final_delivery", False)
            result = await generate(*args, **kwargs)
            if final_delivery and not _unlabelled.get() and result.get("status") == "completed":
                result["final_delivery"] = True
            run = _media_run.get()
            if run is not None:
                result["timing"] = run.timings()
            if _unlabelled.get():
                result["message"] = (
                    f"{result['message']} Tell the user in their language that the AI-generated content label could not be added."
                )
            return result
        finally:
            _unlabelled.reset(token)

    return deliver


def lynxce_media_tools(
    workspace: BackendWorkspace,
    auth: AuthSource,
    *,
    bot_id: str | None = None,
    cloud_tenant: bool = False,
) -> list[Any]:
    """The harness's ``generate_image`` / ``generate_video`` tools, routed to Lynxce."""
    from octop_harness import MediaGenerationConfig  # noqa: PLC0415
    from octop_harness.builtin.tools.media_generation import (  # noqa: PLC0415
        build_media_generation_tools,
    )
    from octop_harness.media import MediaManager  # noqa: PLC0415

    config = MediaGenerationConfig()
    manager = MediaManager(workspace, output_dir=config.output_dir)
    manager.add_provider(
        "lynxce",
        LynxceMediaProvider(
            auth,
            bot_id=bot_id,
            image_model=IMAGE_MODEL if cloud_tenant else None,
            video_model=VIDEO_MODEL if cloud_tenant else None,
        ),
    )
    tools = build_media_generation_tools(workspace, config, manager=manager)
    for tool in tools:
        if cloud_tenant:
            tool.args_schema = create_model(
                "Cloud" + tool.args_schema.__name__,
                __base__=tool.args_schema,
                final_delivery=(
                    bool,
                    Field(
                        default=False,
                        description=(
                            "Set true when the generated attachments complete the user's request "
                            "and only a short final reply remains. Leave false for intermediate "
                            "assets, explicitly requested inspections, or other work still to do."
                        ),
                    ),
                ),
            )
        tool.coroutine = _with_label_notice(tool.coroutine)
    return tools


__all__ = [
    "BOT_ID_HEADER",
    "IMAGE_MODEL",
    "LYNXCE_HOSTS",
    "VIDEO_MODEL",
    "LynxceMediaAuth",
    "LynxceMediaProvider",
    "LynxceMediaTools",
    "lynxce_media_tools",
]
