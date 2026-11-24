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
            return httpx.Response(200, json={"status": "succeeded", "type": "video", "data": data})
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
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
