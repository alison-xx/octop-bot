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

Which model draws and which films is Lynxce's choice, not Octop's: Lynxce's admin orders its
model catalog, and the first image and the first video model in ``GET /models`` are its
defaults (Lynxce's own MCP tools pick the same way). The adapter reads that list, keeps it for a
few minutes, and falls back to fixed models only when the list cannot be read, so a new default
set in Lynxce's admin reaches every Bot without an Octop release.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
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

if TYPE_CHECKING:
    from octop_harness.backends.workspace import BackendWorkspace

logger = logging.getLogger(__name__)

# Used only when Lynxce's model list cannot be read: the defaults Lynxce's admin had set on
# 2026-11-25 (GPT Image 2.6 for images, MiniMax H3 for video), checked against GET /models.
IMAGE_MODEL = "gpt-image-2.6-flare"
VIDEO_MODEL = "ucloud/MiniMax-H3"
# How long one read of Lynxce's defaults is used, and how soon to try again after a failed read.
DEFAULTS_TTL_SECONDS = 600.0
DEFAULTS_RETRY_SECONDS = 60.0
LYNXCE_HOSTS = frozenset({"api.lynxce.cn", "center.lynxce.cn"})

_RUNNING = frozenset({"pending", "submitting", "processing", "uncertain"})
_FAILED = frozenset({"failed", "timeout", "cancelled"})


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
    task_timeout_seconds = 900.0

    def __init__(
        self,
        auth: AuthSource,
        *,
        image_model: str | None = None,
        video_model: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """``image_model`` / ``video_model`` pin a model; left out, Lynxce's defaults are used."""
        self._auth = auth
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
                auth.base_url + "/models", {"Authorization": f"Bearer {auth.bearer}"}
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
        headers = {"Authorization": f"Bearer {auth.bearer}"}
        if method == "POST":
            # A retried submit must not start (and bill) a second task.
            headers["Idempotency-Key"] = uuid4().hex
        try:
            if self._client is not None:
                response = await self._client.request(
                    method, auth.base_url + path, json=json, headers=headers
                )
            else:
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.request(
                        method, auth.base_url + path, json=json, headers=headers
                    )
        except httpx.HTTPError as exc:
            raise MediaGenerationError(
                "Lynxce could not be reached.",
                code="provider_unavailable",
                retryable=True,
                safe_to_resubmit=provider_task_id is None,
                remediation="retry_later",
                provider_task_id=provider_task_id,
            ) from exc
        if response.is_error:
            raise _error(response, provider_task_id=provider_task_id)
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise MediaGenerationError(
                "Lynxce returned an unreadable reply.", provider_task_id=provider_task_id
            )
        return body

    def _update(self, body: dict[str, Any], task_id: str | None) -> MediaJobUpdate:
        status = str(body.get("status") or "")
        if status == "succeeded" and body.get("aigc_label_ready") is False:
            # Still being labelled and rehosted: the links until then are temporary ones that
            # Lynxce deletes, and fetching one can fail. Lynxce asks to poll again.
            return MediaJobUpdate(status="running")
        if status == "succeeded":
            artifacts = _artifacts(body)
            if artifacts:
                return MediaJobUpdate(status="succeeded", artifacts=artifacts)
            raise MediaGenerationError("Lynxce returned no result.", provider_task_id=task_id)
        if status in _RUNNING:
            return MediaJobUpdate(status="pending" if status == "pending" else "running")
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
        if body.get("status") == "succeeded" and (artifacts := _artifacts(body)):
            return MediaSubmission(artifacts=artifacts)
        self._update(body, task_id)  # raises when the task failed at once
        return MediaSubmission(
            task=ProviderTask(task_id=task_id, kind=kind, model=model)  # type: ignore[arg-type]
        )

    async def submit_image(self, request: ImageGenerationRequest) -> MediaSubmission:
        payload: dict[str, Any] = {
            "model": await self._model("image"),
            "prompt": request.prompt,
            "n": request.count,
        }
        if request.size:
            payload["size"] = request.size
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
        return self._update(body, task.task_id)

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
    "the user's Lynxce credits. A video takes a few minutes; before calling generate_video, "
    "tell the user in one short sentence that it is being made and will take a few minutes. "
    "The finished files reach the user as attachments; do not paste their paths or links."
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

    def __init__(self, tools: list[BaseTool]) -> None:
        self.tools = tools

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        return handler(_with_media_prompt(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(_with_media_prompt(request))


def lynxce_media_tools(workspace: BackendWorkspace, auth: AuthSource) -> list[Any]:
    """The harness's ``generate_image`` / ``generate_video`` tools, routed to Lynxce."""
    from octop_harness import MediaGenerationConfig  # noqa: PLC0415
    from octop_harness.builtin.tools.media_generation import (  # noqa: PLC0415
        build_media_generation_tools,
    )
    from octop_harness.media import MediaManager  # noqa: PLC0415

    config = MediaGenerationConfig()
    manager = MediaManager(workspace, output_dir=config.output_dir)
    manager.add_provider("lynxce", LynxceMediaProvider(auth))
    return build_media_generation_tools(workspace, config, manager=manager)


__all__ = [
    "IMAGE_MODEL",
    "LYNXCE_HOSTS",
    "VIDEO_MODEL",
    "LynxceMediaAuth",
    "LynxceMediaProvider",
    "LynxceMediaTools",
    "lynxce_media_tools",
]
