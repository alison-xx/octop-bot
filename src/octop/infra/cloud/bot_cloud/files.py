"""The object store behind Octop Bot cloud mode (any S3-compatible service: Tencent COS, Aliyun OSS, MinIO).

Agent workspaces live under ``users/<uid>/agents/<agent_id>/`` (the harness ``s3`` backend, which
stores JSON-wrapped files). Files a user downloads are copied out as plain bytes under
``downloads/<uid>/<ulid>/<name>`` and handed over as short-lived signed URLs, so the bytes come
straight from the store (and its CDN) instead of through this server. Give the bucket a lifecycle
rule that expires ``downloads/`` after a day or two.

Credentials come from the environment only; they never reach the database or an agent's config.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.ulid import new_ulid

BACKEND_TYPE = "bot_cloud"
DOWNLOAD_TTL_SECONDS = 600


@dataclass(frozen=True)
class FileStoreConfig:
    bucket: str
    access_key_id: str
    secret_access_key: str
    endpoint_url: str | None
    region: str | None
    addressing: Literal["virtual", "path"]
    prefix: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> FileStoreConfig | None:
        """``OCTOP_FILE_STORE_*``; ``None`` until bucket and keys are all set."""
        source = os.environ if env is None else env

        def read(name: str) -> str:
            return (source.get(f"OCTOP_FILE_STORE_{name}") or "").strip()

        bucket, key, secret = read("BUCKET"), read("ACCESS_KEY_ID"), read("SECRET_ACCESS_KEY")
        if not (bucket and key and secret):
            return None
        endpoint = read("ENDPOINT")
        if endpoint and "://" not in endpoint:
            endpoint = f"https://{endpoint}"
        # COS and OSS only accept virtual-hosted requests; MinIO usually wants path style.
        addressing: Literal["virtual", "path"] = (
            "path" if read("ADDRESSING") == "path" else "virtual"
        )
        prefix = read("PREFIX").strip("/")
        return cls(
            bucket=bucket,
            access_key_id=key,
            secret_access_key=secret,
            endpoint_url=endpoint or None,
            region=read("REGION") or None,
            addressing=addressing,
            prefix=f"{prefix}/" if prefix else "",
        )


def require_config() -> FileStoreConfig:
    config = FileStoreConfig.from_env()
    if config is None:
        raise OctopError(ErrorCode.INTERNAL_ERROR, "the cloud file store is not configured")
    return config


def agent_backend(user_id: int, agent_id: str) -> dict[str, Any]:
    """What a cloud agent's ``config.backend`` holds: a reference, no secrets."""
    return {"type": BACKEND_TYPE, "user_id": int(user_id), "agent_id": agent_id}


def agent_prefix(config: FileStoreConfig, user_id: int, agent_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", agent_id):
        raise OctopError(ErrorCode.FORBIDDEN, "invalid agent id")
    return f"{config.prefix}users/{int(user_id)}/agents/{agent_id}/"


def harness_spec(spec: Mapping[str, Any], config: FileStoreConfig | None = None) -> dict[str, Any]:
    """Expand a ``bot_cloud`` reference into the harness ``s3`` backend spec."""
    store = config or require_config()
    user_id, agent_id = spec.get("user_id"), spec.get("agent_id")
    if not isinstance(user_id, int) or not isinstance(agent_id, str):
        raise ValueError("bot_cloud backend needs user_id and agent_id")
    out: dict[str, Any] = {
        "type": "s3",
        "bucket": store.bucket,
        "access_key_id": store.access_key_id,
        "secret_access_key": store.secret_access_key,
        "prefix": agent_prefix(store, user_id, agent_id),
        "addressing_style": store.addressing,
    }
    if store.endpoint_url:
        out["endpoint_url"] = store.endpoint_url
    if store.region:
        out["region"] = store.region
    return out


def _client(config: FileStoreConfig) -> Any:
    import boto3  # noqa: PLC0415
    from botocore.config import Config  # noqa: PLC0415

    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": config.addressing},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def safe_filename(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip() or "file"
    base = re.sub(r"[\x00-\x1f\x7f]", "", base)
    return base[:180]


def download_key(config: FileStoreConfig, user_id: int, filename: str) -> str:
    return f"{config.prefix}downloads/{int(user_id)}/{new_ulid()}/{safe_filename(filename)}"


def publish_download(
    user_id: int,
    filename: str,
    data: bytes,
    content_type: str | None,
    *,
    config: FileStoreConfig | None = None,
    client: Any | None = None,
) -> str:
    """Store a copy for download and return a signed URL that saves it as ``filename``."""
    store = config or require_config()
    s3 = client or _client(store)
    key = download_key(store, user_id, filename)
    s3.put_object(
        Bucket=store.bucket,
        Key=key,
        Body=data,
        ContentType=content_type or "application/octet-stream",
    )
    name = safe_filename(filename)
    disposition = f"attachment; filename*=UTF-8''{quote(name)}"
    url: str = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": store.bucket, "Key": key, "ResponseContentDisposition": disposition},
        ExpiresIn=DOWNLOAD_TTL_SECONDS,
    )
    return url
