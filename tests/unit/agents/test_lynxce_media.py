"""Lynxce image and video generation through the harness media tools."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from deepagents.backends.local_shell import LocalShellBackend
from octop_harness.backends.workspace import BackendWorkspace
from octop_harness.media import (
    ImageGenerationRequest,
    MediaGenerationError,
    MediaManager,
    VideoGenerationRequest,
)

from octop.infra.agents.providers import lynxce_media
from octop.infra.agents.providers.lynxce_media import (
    IMAGE_MODEL,
    VIDEO_MODEL,
    LynxceMediaAuth,
    LynxceMediaProvider,
    lynxce_media_tools,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 32
BASE = "https://api.lynxce.cn/api/v1"


# Lynxce's catalog order: the first image and the first video model are its defaults.
MODELS = {
    "object": "list",
    "data": [
        {"id": "deepseek-v4", "modality": "chat"},
        {"id": "gpt-image-2.6-flare", "modality": "image"},
        {"id": "gpt-image-2.5", "modality": "image"},
        {"id": "ucloud/MiniMax-H3", "modality": "video"},
        {"id": "seedance", "modality": "video"},
    ],
}


@pytest.fixture(autouse=True)
def _fresh_defaults() -> None:
    lynxce_media._defaults_cache.clear()


async def _auth() -> LynxceMediaAuth:
    return LynxceMediaAuth(BASE, "sk-test")


class Gateway:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any], httpx.Headers]] = []
        self.polls = 0
        self.model_reads = 0
        self.models: httpx.Response = httpx.Response(200, json=MODELS)
        self.fail: httpx.Response | None = None

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.host == "cdn.example.com":
            assert "Authorization" not in req.headers  # signed links get no credential
            return httpx.Response(200, content=MP4 if req.url.path.endswith(".mp4") else PNG)
        assert req.headers["Authorization"] == "Bearer sk-test"
        if req.method == "GET" and req.url.path == "/api/v1/models":
            self.model_reads += 1
            return self.models
        if self.fail is not None:
            return self.fail
        if req.method == "POST":
            self.posts.append((req.url.path, json.loads(req.content), req.headers))
            kind = "video" if "videos" in req.url.path else "image"
            return httpx.Response(200, json={"id": f"{kind}-1", "status": "processing", "data": []})
        self.polls += 1
        if self.polls < 2:
            return httpx.Response(200, json={"id": "x", "status": "processing", "progress": 40})
        if req.url.path.endswith("/video-1"):
            data = [{"url": "https://cdn.example.com/out.mp4"}]
            return httpx.Response(
                200,
                json={
                    "status": "succeeded",
                    "aigc_label_ready": True,
                    "type": "video",
                    "data": data,
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
                "aigc_label_ready": True,
                "type": "image",
                "data": [{"url": "https://cdn.example.com/a.png"}],
            },
        )


def _provider(gateway: Gateway) -> LynxceMediaProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(gateway))
    provider = LynxceMediaProvider(_auth, client=client)
    provider.poll_interval_seconds = 0.0
    return provider


def _workspace(root: Path) -> BackendWorkspace:
    return BackendWorkspace(LocalShellBackend(root_dir=str(root), virtual_mode=False), str(root))


async def test_an_image_is_submitted_polled_and_downloaded(tmp_path: Path) -> None:
    gateway = Gateway()
    manager = MediaManager(_workspace(tmp_path), output_dir="generated")
    manager.add_provider("lynxce", _provider(gateway))
    result = await manager.generate_image(ImageGenerationRequest(prompt="一只猫", count=1))
    path, body, headers = gateway.posts[0]
    assert path == "/api/v1/images/generations"
    assert body == {"model": "gpt-image-2.6-flare", "prompt": "一只猫", "n": 1}
    assert result.model == "gpt-image-2.6-flare"
    assert headers["Idempotency-Key"]
    assert result.artifacts[0].media_type == "image/png"
    assert (tmp_path / result.artifacts[0].path).read_bytes() == PNG


async def test_a_video_request_and_its_result() -> None:
    gateway = Gateway()
    provider = _provider(gateway)
    submission = await provider.submit_video(
        VideoGenerationRequest(prompt="海浪", first_frame="https://cdn.example.com/f.png")
    )
    assert submission.task is not None and submission.task.task_id == "video-1"
    assert gateway.posts[0][1] == {
        "model": "ucloud/MiniMax-H3",
        "prompt": "海浪",
        "duration": 5,
        "resolution": "720p",
        "aspect_ratio": "16:9",
        "images": ["https://cdn.example.com/f.png"],
    }
    assert (await provider.poll(submission.task)).status == "running"
    done = await provider.poll(submission.task)
    assert done.status == "succeeded"
    media = await provider.load_artifact(done.artifacts[0])
    assert (media.media_type, media.extension) == ("video/mp4", "mp4")


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (402, "insufficient_balance", "insufficient_credits"),
        (402, "api_key_credit_limit_reached", "credit_limit_reached"),
        (403, "api_key_scope_forbidden", "media_scope_required"),
    ],
)
async def test_credit_and_scope_refusals_stay_recognizable(
    status: int, code: str, expected: str
) -> None:
    gateway = Gateway()
    gateway.fail = httpx.Response(status, json={"error": {"code": code, "message": "积分不足"}})
    with pytest.raises(MediaGenerationError) as caught:
        await _provider(gateway).submit_image(ImageGenerationRequest(prompt="猫"))
    assert caught.value.code == expected
    assert caught.value.provider_code == code
    assert caught.value.http_status == status


async def test_a_failed_task_reports_lynxces_reason() -> None:
    gateway = Gateway()
    provider = _provider(gateway)
    submission = await provider.submit_image(ImageGenerationRequest(prompt="猫"))
    assert submission.task is not None
    gateway.fail = httpx.Response(
        200,
        json={"status": "failed", "error": {"code": "content_rejected", "message": "内容不合规"}},
    )
    with pytest.raises(MediaGenerationError, match="内容不合规"):
        await provider.poll(submission.task)


def test_the_tools_are_the_harness_media_tools(tmp_path: Path) -> None:
    tools = lynxce_media_tools(_workspace(tmp_path), _auth)
    assert [t.name for t in tools] == ["generate_image", "generate_video"]


def test_the_prompt_no_longer_says_media_is_not_configured() -> None:
    from langchain_core.messages import SystemMessage

    from octop.infra.agents.providers import lynxce_media

    harness = "Base." + lynxce_media._HARNESS_NOT_CONFIGURED + " More."
    request = SimpleNamespace(
        messages=[],
        system_message=SystemMessage(content=harness),
        override=lambda **kw: SimpleNamespace(**kw),
    )
    out = lynxce_media._with_media_prompt(request)  # type: ignore[arg-type]
    text = "".join(b["text"] for b in out.system_message.content_blocks)
    assert "not configured" not in text
    assert text.startswith("Base. More.") and "generate_video" in text


async def test_a_server_with_a_lynxce_api_key_uses_it(monkeypatch: pytest.MonkeyPatch) -> None:
    from octop.infra.agents.providers import lynxce

    monkeypatch.delenv("OCTOP_BOT_CLOUD", raising=False)
    monkeypatch.delenv("OCTOP_BOT_DESKTOP", raising=False)
    rows = [
        SimpleNamespace(enabled=1, api_key="sk-other", base_url="https://api.example.com/v1"),
        SimpleNamespace(enabled=0, api_key="sk-off", base_url="https://api.lynxce.cn/api/v1"),
        SimpleNamespace(enabled=1, api_key="sk-lynxce", base_url="https://api.lynxce.cn/api/v1/"),
    ]
    services: Any = SimpleNamespace(provider_repo=SimpleNamespace(list_all=lambda: rows))
    assert lynxce.media_source(services, None) == "api_key"
    auth = await lynxce.media_auth(services, None)
    assert (auth.base_url, auth.bearer) == ("https://api.lynxce.cn/api/v1", "sk-lynxce")
    rows.pop()
    assert lynxce.media_source(services, None) is None


async def test_a_result_still_being_labelled_is_not_done_yet() -> None:
    gateway = Gateway()
    provider = _provider(gateway)
    submission = await provider.submit_image(ImageGenerationRequest(prompt="猫"))
    assert submission.task is not None
    temporary = [{"url": "https://upstream.example.com/tmp.png"}]
    gateway.fail = httpx.Response(
        200, json={"status": "succeeded", "aigc_label_ready": False, "data": temporary}
    )
    assert (await provider.poll(submission.task)).status == "running"
    gateway.fail = httpx.Response(
        200,
        json={
            "status": "succeeded",
            "aigc_label_ready": True,
            "data": [{"url": "https://cdn.example.com/a.png"}],
        },
    )
    assert (await provider.poll(submission.task)).status == "succeeded"


async def test_lynxces_defaults_are_read_once_and_follow_its_admin() -> None:
    gateway = Gateway()
    provider = _provider(gateway)
    await provider.submit_image(ImageGenerationRequest(prompt="猫"))
    await provider.submit_video(VideoGenerationRequest(prompt="海浪"))
    assert [body["model"] for _, body, _ in gateway.posts] == [
        "gpt-image-2.6-flare",
        "ucloud/MiniMax-H3",
    ]
    assert gateway.model_reads == 1  # one read serves both kinds for a while
    assert (provider.image_model, provider.video_model) == (
        "gpt-image-2.6-flare",
        "ucloud/MiniMax-H3",
    )

    # Lynxce's admin moves another model to the top: the next read after the cache picks it up.
    gateway.models = httpx.Response(200, json={"data": [{"id": "qwen-image", "modality": "image"}]})
    lynxce_media._defaults_cache.clear()
    await provider.submit_image(ImageGenerationRequest(prompt="狗"))
    assert gateway.posts[-1][1]["model"] == "qwen-image"


@pytest.mark.parametrize(
    "models",
    [
        httpx.Response(503, json={"error": {"code": "unavailable"}}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"data": [{"id": "deepseek-v4", "modality": "chat"}]}),
    ],
)
async def test_an_unreadable_model_list_falls_back_and_says_so(
    models: httpx.Response, caplog: pytest.LogCaptureFixture
) -> None:
    gateway = Gateway()
    gateway.models = models
    provider = _provider(gateway)
    await provider.submit_image(ImageGenerationRequest(prompt="猫"))
    await provider.submit_video(VideoGenerationRequest(prompt="海浪"))
    assert [body["model"] for _, body, _ in gateway.posts] == [IMAGE_MODEL, VIDEO_MODEL]
    assert "No Lynxce default image model" in caplog.text
    assert gateway.model_reads == 1  # the failure is cached briefly too, not retried per call


async def test_a_pinned_model_skips_lynxces_list() -> None:
    gateway = Gateway()
    client = httpx.AsyncClient(transport=httpx.MockTransport(gateway))
    provider = LynxceMediaProvider(_auth, image_model="wan2.7-image", client=client)
    await provider.submit_image(ImageGenerationRequest(prompt="猫"))
    assert gateway.posts[0][1]["model"] == "wan2.7-image"
    assert gateway.model_reads == 0


async def test_media_calls_say_octop_bot_and_which_bot() -> None:
    seen: list[httpx.Headers] = []
    gateway = Gateway()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host != "cdn.example.com":
            seen.append(req.headers)
        return gateway(req)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = LynxceMediaProvider(_auth, client=client, bot_id="0W9CAX")
    await provider.submit_image(ImageGenerationRequest(prompt="猫"))
    assert len(seen) == 2  # the model list and the submit
    for headers in seen:
        assert headers["X-Lynxce-App"] == "octopbot"
        assert headers["X-Lynxce-Bot-Id"] == "0W9CAX"

    plain = Gateway()
    plain_client = httpx.AsyncClient(transport=httpx.MockTransport(plain))
    await LynxceMediaProvider(_auth, client=plain_client).submit_image(
        ImageGenerationRequest(prompt="猫")
    )
    assert "X-Lynxce-Bot-Id" not in plain.posts[0][2]
    assert plain.posts[0][2]["X-Lynxce-App"] == "octopbot"


def test_chat_model_calls_carry_the_bot_id() -> None:
    from octop.infra.agents.providers.lynxce import AccountModel, CloudAccountModel

    for model in (AccountModel(1, "conn", "deepseek"), CloudAccountModel(1, "conn", "deepseek")):
        assert model.provider(None, "0W9CAX").headers == {
            "X-Lynxce-App": "octopbot",
            "X-Lynxce-Bot-Id": "0W9CAX",
        }
        assert model.provider(None).headers == {"X-Lynxce-App": "octopbot"}


def test_cloud_group_uses_direct_answers_unless_reasoning_is_explicit() -> None:
    from octop.infra.agents.providers.lynxce import CloudAccountModel

    model = CloudAccountModel(1, "conn", "tencent/auto")
    group = {"source": "octop_bot_group/octop-bot"}
    key = "octop_reasoning_overrides"
    assert model.request(group)["configurable"][key] == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }
    explicit = {"extra_body": {"thinking": {"type": "enabled"}}}
    assert (
        model.request({**group, "configurable": {key: explicit}})["configurable"][key] == explicit
    )
    assert key not in model.request({"source": "dashboard/octop-ws"})["configurable"]
    assert key not in CloudAccountModel(1, "conn", "other").request(group)["configurable"]


def test_final_media_receipt_preserves_followups_and_compound_tasks() -> None:
    from langchain_core.messages import HumanMessage, ToolMessage

    def result(name: str, body: dict[str, object]) -> ToolMessage:
        return ToolMessage(content=json.dumps(body), name=name, tool_call_id=name)

    completed = result(
        "generate_image", {"final_delivery": True, "images": [{"path": "generated/ok.png"}]}
    )
    for messages in (
        [completed, HumanMessage(content="继续编辑")],
        [result("task_plan", {}), completed],
        [completed, result("generate_video", {"status": "failed"})],
        [result("generate_image", {"status": "completed"})],
    ):
        assert not lynxce_media._final_media_reply(SimpleNamespace(messages=messages), "zh")


@pytest.mark.parametrize(
    ("command", "kind", "count", "model"),
    [
        ("给我画一张海浪图", "image", 1, IMAGE_MODEL),
        ("同一主题给我做三张海浪图", "image", 3, IMAGE_MODEL),
        ("做一段海浪短视频", "video", 1, VIDEO_MODEL),
    ],
)
async def test_cloud_graph_publishes_progress_and_delivers_every_artifact(
    command: str, kind: str, count: int, model: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import Mock

    from deepagents.backends.filesystem import FilesystemBackend
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage, ToolMessage
    from tests.support.fault_graph import FaultModel

    from octop.infra.cloud.computers.backend import CloudComputer

    posts = []
    polls = iter(
        [
            {"status": "running", "progress": 35},
            {"status": "succeeded", "aigc_label_ready": False},
            {
                "status": "succeeded",
                "aigc_label_ready": True,
                "data": [{"url": f"https://cdn.example.com/{i}"} for i in range(count)],
            },
        ]
    )

    def gateway(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.example.com":
            assert "Authorization" not in request.headers
            return httpx.Response(
                200, content=(PNG if kind == "image" else MP4) + request.url.path.encode()
            )
        if request.method == "POST":
            assert request.url.path.endswith(f"/{kind}s/generations")
            posts.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "job", "status": "queued"})
        assert request.url.path.endswith("/generations/job")
        return httpx.Response(200, json={"id": "job", "type": kind, **next(polls)})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(gateway), **kw)
    )
    monkeypatch.setattr(LynxceMediaProvider, "poll_interval_seconds", 0.01)
    # Only wake-hook registration is available: compute, desktop and shell I/O must never run.
    computer_manager = Mock(spec_set=["on_wake"])
    store = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)
    backend = CloudComputer(computer_manager, user_id=1, agent_id="qa", store=store)
    workspace = BackendWorkspace(backend, str(tmp_path))
    tools = lynxce_media_tools(workspace, _auth, cloud_tenant=True)
    call = {
        "name": f"generate_{kind}",
        "id": "test-call",
        "args": {
            "prompt": command,
            "final_delivery": True,
            **({"count": count} if kind == "image" else {}),
        },
    }
    graph = create_agent(
        model=FaultModel(
            mode="normal",
            responses=[AIMessage(content="", tool_calls=[call]), AIMessage(content="已完成")],
        ),
        middleware=[lynxce_media.LynxceMediaTools(tools)],
    )
    frames, messages = [], []
    async for stream, data in graph.astream(
        {"messages": [("user", command)]}, stream_mode=["values", "custom"]
    ):
        if stream == "custom":
            frames.append(data)
        else:
            messages = data["messages"]
    assert [p["model"] for p in posts] == [model]
    if kind == "image":
        assert posts[0]["n"] == count
    assert [f["phase"] for f in frames] == [
        "submitting",
        "queued",
        "generating",
        "finalizing",
        "delivering",
    ]
    assert frames[2]["percent"] == 35 and all(f["call_id"] == "test-call" for f in frames)
    reply = next(m for m in messages if isinstance(m, ToolMessage))
    result = json.loads(reply.content)
    assert result["status"] == "completed"
    assert result["final_delivery"] is True
    final = SimpleNamespace(messages=messages[: messages.index(reply) + 1])
    assert lynxce_media._final_media_reply(final, "zh")
    assert f"已交付 {count} 个生成文件" in messages[-1].content
    files = result[kind + "s"]
    assert len({row["path"] for row in files}) == count
    assert [(tmp_path / row["path"]).read_bytes() for row in files] == [
        (PNG if kind == "image" else MP4) + f"/{i}".encode() for i in range(count)
    ]
    timing = result["timing"]
    assert 0 <= timing["submit_ms"] <= timing["ready_ms"] <= timing["total_ms"]
    assert abs(timing["ready_ms"] + timing["delivery_ms"] - timing["total_ms"]) <= 1


async def test_uncertain_media_submit_reuses_its_key() -> None:
    keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        keys.append(request.headers["Idempotency-Key"])
        if len(keys) == 1:
            raise httpx.ReadTimeout("lost response")
        return httpx.Response(200, json={"id": "original", "status": "running"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = LynxceMediaProvider(_auth, image_model=IMAGE_MODEL, client=client)
        submission = await provider.submit_image(ImageGenerationRequest(prompt="猫"))
    assert submission.task and submission.task.task_id == "original"
    assert len(keys) == 2 and keys[0] == keys[1]


@pytest.mark.parametrize("expired", [True, False])
async def test_label_failure_or_deadline_delivers_with_notice(expired: bool) -> None:
    from octop_harness.media.models import ProviderTask

    provider = _provider(Gateway())
    task = ProviderTask("id", "image", IMAGE_MODEL)
    task.metadata["finalizing_since"] = str(
        lynxce_media.time.monotonic() - (1801 if expired else 1)
    )

    async def generate() -> dict[str, object]:
        update = provider._update(
            {
                "status": "succeeded",
                "aigc_label_ready": False,
                "error": None if expired else {"code": "aigc_label_failed"},
                "data": [{"url": "https://cdn.example.com/image.png"}],
            },
            task,
        )
        assert update.status == "succeeded"
        return {"message": "Generated an image."}

    result = await lynxce_media._with_label_notice(generate)()
    assert "label could not be added" in str(result["message"])
