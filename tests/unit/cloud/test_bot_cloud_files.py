"""The S3-compatible store behind Octop Bot cloud."""

from typing import Any
from urllib.parse import unquote

import pytest

from octop.infra.backend.resolver import resolve_agent_backend_spec
from octop.infra.cloud.bot_cloud import files
from octop.infra.errors import OctopError

ENV = {
    "OCTOP_FILE_STORE_BUCKET": "octop-bot-files-1250000000",
    "OCTOP_FILE_STORE_ACCESS_KEY_ID": "AKID",
    "OCTOP_FILE_STORE_SECRET_ACCESS_KEY": "secret",
    "OCTOP_FILE_STORE_ENDPOINT": "cos.ap-guangzhou.myqcloud.com",
    "OCTOP_FILE_STORE_REGION": "ap-guangzhou",
    "OCTOP_FILE_STORE_PREFIX": "/prod/",
}


def test_config_needs_bucket_and_keys() -> None:
    assert files.FileStoreConfig.from_env({}) is None
    assert files.FileStoreConfig.from_env({"OCTOP_FILE_STORE_BUCKET": "b"}) is None
    config = files.FileStoreConfig.from_env(ENV)
    assert config is not None
    assert config.endpoint_url == "https://cos.ap-guangzhou.myqcloud.com"
    assert config.addressing == "virtual"
    assert config.prefix == "prod/"


def test_agent_backends_reference_the_store_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    ref = files.agent_backend(7, "AbC123")
    assert ref == {"type": "bot_cloud", "user_id": 7, "agent_id": "AbC123"}
    assert "secret" not in str(ref)
    spec = resolve_agent_backend_spec(ref, repo=None)
    assert spec["type"] == "s3"
    assert spec["prefix"] == "prod/users/7/agents/AbC123/"
    assert spec["bucket"] == ENV["OCTOP_FILE_STORE_BUCKET"]
    assert spec["addressing_style"] == "virtual"
    with pytest.raises(OctopError):
        files.harness_spec({"type": "bot_cloud", "user_id": 7, "agent_id": "../x"})


class FakeS3:
    def __init__(self) -> None:
        self.put: dict[str, Any] = {}

    def put_object(self, **kwargs: Any) -> None:
        self.put = kwargs

    def generate_presigned_url(self, op: str, *, Params: dict[str, Any], ExpiresIn: int) -> str:  # noqa: N803
        assert op == "get_object" and ExpiresIn == files.DOWNLOAD_TTL_SECONDS
        return f"https://signed/{Params['Key']}?cd={Params['ResponseContentDisposition']}"


def test_downloads_are_plain_copies_under_the_users_prefix() -> None:
    config = files.FileStoreConfig.from_env(ENV)
    assert config is not None
    s3 = FakeS3()
    url = files.publish_download(
        7, "../../报告 v1.pdf", b"%PDF", "application/pdf", config=config, client=s3
    )
    key = s3.put["Key"]
    assert key.startswith("prod/downloads/7/") and key.endswith("/报告 v1.pdf")
    assert s3.put["Body"] == b"%PDF" and s3.put["ContentType"] == "application/pdf"
    assert url.startswith("https://signed/prod/downloads/7/")
    assert unquote(url.split("cd=", 1)[1]).startswith("attachment; filename*=UTF-8''")
