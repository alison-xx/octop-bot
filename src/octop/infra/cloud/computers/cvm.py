"""Tencent Cloud CVM: one cloud computer per Octop Bot, on our own desktop image.

Same contract as the AGS driver, about a quarter of the compute price. The image
(``deploy/cvm/image/setup.sh``) runs the same OSWorld desktop server AGS sandboxes run, so
commands, files, screenshots, the accessibility tree, the clipboard and the screen all reuse
:class:`AgsDriver`'s data plane; only the lifecycle and the way in differ:

- Lifecycle is plain CVM: ``RunInstances`` / ``StopInstances`` (``STOP_CHARGING``: a stopped
  computer pays for its disk only) / ``StartInstances`` / ``TerminateInstances``. A stopped
  instance loses its public IP, so the address is looked up again after every start.
- Each instance's nginx (port 443, the only port its security group opens, and only to this
  server) checks an access token and serves TLS with a certificate issued for that instance.
  Both come in the first-boot user data. The token is an HMAC of a random per-instance
  reference kept in a tag, and the certificate is signed by a CA derived from the instance
  secret (``INSTANCE_SECRET``, or the CAM secret when that is unset), so a server needs no
  state beyond its configuration to reach every computer it started.

Configured from the environment (``OCTOP_CVM_*``): ``SECRET_ID`` / ``SECRET_KEY`` (a CAM
sub-account with CVM, VPC, TAT and ``finance:trade``), ``REGION`` (default ``ap-guangzhou``),
``IMAGE_ID``, ``VPC_ID``, ``SUBNETS`` (``zone:subnet,...``; tried in order when a zone has no
stock), ``SECURITY_GROUP``, ``TYPE`` / ``TYPE_PRO`` (default ``SA9.LARGE8`` /
``SA9.2XLARGE16``), ``DISK_GB`` (default 40), ``BANDWIDTH`` (Mbps, default 50),
``INSTANCE_SECRET`` (optional: the seed for instance tokens and certificates; set it to the
old ``SECRET_KEY`` before rotating the CAM key, so existing computers stay reachable).
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import logging
import os
import secrets
import ssl
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from octop.infra.cloud.computers.driver import AgsDriver, Instance, Spec, State

logger = logging.getLogger(__name__)

MANAGED_TAG = "octop-computer"
REF_TAG = "octop-ref"
# Where the image's nginx sends each local port.
_GATEWAY = "/p/{port}"
# Errors that mean "not in this zone": no stock there, or the account's instance quota for that
# zone is used up. Either way the next zone may still take the computer.
_ZONE_ERRORS = (
    "ResourceInsufficient",
    "ResourcesSoldOut",
    "InstancesSoldOut",
    "NoAvailableZone",
    "LimitExceeded.InstanceQuota",
)


@dataclass(frozen=True)
class CvmConfig:
    secret_id: str
    secret_key: str = field(repr=False)
    region: str
    image_id: str
    vpc_id: str
    subnets: tuple[tuple[str, str], ...]
    security_group: str
    types: Mapping[Spec, str]
    disk_gb: int
    bandwidth: int
    instance_secret: str = field(default="", repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> CvmConfig | None:
        source = os.environ if env is None else env

        def read(name: str) -> str:
            return (source.get(f"OCTOP_CVM_{name}") or "").strip()

        required = [read(n) for n in ("SECRET_ID", "SECRET_KEY", "IMAGE_ID", "VPC_ID", "SUBNETS")]
        if not all(required) or not read("SECURITY_GROUP"):
            return None
        subnets = tuple(
            (zone.strip(), subnet.strip())
            for zone, _, subnet in (item.partition(":") for item in read("SUBNETS").split(","))
            if zone.strip() and subnet.strip()
        )
        if not subnets:
            return None
        standard = read("TYPE") or "SA9.LARGE8"
        return cls(
            secret_id=read("SECRET_ID"),
            secret_key=read("SECRET_KEY"),
            region=read("REGION") or "ap-guangzhou",
            image_id=read("IMAGE_ID"),
            vpc_id=read("VPC_ID"),
            subnets=subnets,
            security_group=read("SECURITY_GROUP"),
            types={"standard": standard, "pro": read("TYPE_PRO") or "SA9.2XLARGE16"},
            disk_gb=int(read("DISK_GB") or 40),
            bandwidth=int(read("BANDWIDTH") or 50),
            instance_secret=read("INSTANCE_SECRET"),
        )

    def derive(self, purpose: str) -> bytes:
        """A stable secret for ``purpose``, derived from the instance secret (the CAM secret when
        none is set), so rotating the CAM key alone leaves every computer reachable."""
        seed = self.instance_secret or self.secret_key
        return hmac.new(seed.encode(), f"octop-cvm:{purpose}".encode(), hashlib.sha256).digest()


_ACTIVE = {"RUNNING"}
_STARTING = {"PENDING", "STARTING", "REBOOTING"}
_STOPPED = {"STOPPED", "STOPPING"}


def cvm_state(status: str | None) -> State:
    """CVM instance state → manager state. Stopped (no compute charge) is the paused state."""
    value = (status or "").upper()
    if value in _ACTIVE:
        return "running"
    if value in _STARTING:
        return "starting"
    if value in _STOPPED:
        return "paused"
    return "gone"


class InstanceCA:
    """A private CA whose key is derived from the CAM secret; issues one cert per instance."""

    def __init__(self, seed: bytes) -> None:
        from cryptography import x509  # noqa: PLC0415
        from cryptography.hazmat.primitives import hashes  # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415
        from cryptography.x509.oid import NameOID  # noqa: PLC0415

        order = int("FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551", 16)
        self._key = ec.derive_private_key(
            int.from_bytes(seed, "big") % (order - 1) + 1, ec.SECP256R1()
        )
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Octop Bot computers CA")])
        start = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        self.cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(self._key.public_key())
            .serial_number(int.from_bytes(hashlib.sha256(seed).digest()[:16], "big"))
            .not_valid_before(start)
            .not_valid_after(start + dt.timedelta(days=365 * 30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(self._key, hashes.SHA256())
        )
        self._name = name

    @cached_property
    def pem(self) -> str:
        from cryptography.hazmat.primitives.serialization import Encoding  # noqa: PLC0415

        return self.cert.public_bytes(Encoding.PEM).decode()

    def issue(self, common_name: str) -> tuple[str, str]:
        """A fresh key and certificate for one instance, as PEM ``(cert, key)``."""
        from cryptography import x509  # noqa: PLC0415
        from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415
        from cryptography.x509.oid import NameOID  # noqa: PLC0415

        key = ec.generate_private_key(ec.SECP256R1())
        now = dt.datetime.now(dt.UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
            .issuer_name(self._name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=365 * 10))
            .sign(self._key, hashes.SHA256())
        )
        return (
            cert.public_bytes(serialization.Encoding.PEM).decode(),
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
        )

    def context(self) -> ssl.SSLContext:
        """Trusts only this CA; instances are reached by IP, so the name is not checked."""
        context = ssl.create_default_context(cadata=self.pem)
        context.check_hostname = False
        return context


def first_boot(token: str, cert: str, key: str) -> str:
    """User data: install this instance's token and certificate, then start nginx with them."""
    pack = base64.b64encode
    return "\n".join(
        [
            "#!/bin/bash",
            "set -e",
            "install -d -m 700 /etc/octop",
            f"echo {pack(cert.encode()).decode()} | base64 -d > /etc/octop/cert.pem",
            f"echo {pack(key.encode()).decode()} | base64 -d > /etc/octop/key.pem",
            f"printf %s {token} > /etc/octop/token",
            "chmod 600 /etc/octop/key.pem /etc/octop/token",
            f"sed 's/__TOKEN__/{token}/' /etc/octop/nginx.conf.template > /etc/nginx/conf.d/octop.conf",
            "systemctl restart nginx",
            "",
        ]
    )


class CvmDriver(AgsDriver):
    def __init__(self, config: CvmConfig) -> None:
        super().__init__(config=None)  # type: ignore[arg-type]
        self._cvm_config = config
        self._token_key = config.derive("token")
        self._ca = InstanceCA(config.derive("ca"))
        self._addresses: dict[str, str] = {}
        self._refs: dict[str, str] = {}
        self._addr_lock = threading.Lock()

    # -- control plane -----------------------------------------------------------

    def _api(self) -> Any:
        if self._client is None:
            from tencentcloud.common.credential import Credential  # noqa: PLC0415
            from tencentcloud.cvm.v20170312 import cvm_client  # noqa: PLC0415

            self._client = cvm_client.CvmClient(
                Credential(self._cvm_config.secret_id, self._cvm_config.secret_key),
                self._cvm_config.region,
            )
        return self._client

    @staticmethod
    def _models() -> Any:
        from tencentcloud.cvm.v20170312 import models  # noqa: PLC0415

        return models

    def _token_for(self, ref: str) -> str:
        return hmac.new(self._token_key, ref.encode(), hashlib.sha256).hexdigest()

    def start(self, *, spec: Spec, labels: Mapping[str, str]) -> str:
        models = self._models()
        config = self._cvm_config
        ref = secrets.token_hex(16)
        cert, key = self._ca.issue(f"octop-computer-{ref[:8]}")
        tags = []
        for name, value in {**labels, MANAGED_TAG: "1", REF_TAG: ref}.items():
            tag = models.Tag()
            tag.Key, tag.Value = name, value
            tags.append(tag)
        last: Exception | None = None
        for zone, subnet in config.subnets:
            run = models.RunInstancesRequest()
            run.InstanceChargeType = "POSTPAID_BY_HOUR"
            run.InstanceType = config.types[spec]
            run.ImageId = config.image_id
            run.Placement = models.Placement()
            run.Placement.Zone = zone
            run.SystemDisk = models.SystemDisk()
            run.SystemDisk.DiskType, run.SystemDisk.DiskSize = "CLOUD_BSSD", config.disk_gb
            run.VirtualPrivateCloud = models.VirtualPrivateCloud()
            run.VirtualPrivateCloud.VpcId, run.VirtualPrivateCloud.SubnetId = config.vpc_id, subnet
            run.SecurityGroupIds = [config.security_group]
            run.InternetAccessible = models.InternetAccessible()
            run.InternetAccessible.InternetChargeType = "TRAFFIC_POSTPAID_BY_HOUR"
            run.InternetAccessible.InternetMaxBandwidthOut = config.bandwidth
            run.InternetAccessible.PublicIpAssigned = True
            run.LoginSettings = models.LoginSettings()
            # Nobody logs in: the only open port is nginx's, and only to this server.
            run.LoginSettings.Password = "Oc" + secrets.token_urlsafe(18) + "9!"
            run.InstanceName = "octop-" + (labels.get("octop-bot") or ref[:8])
            run.UserData = base64.b64encode(
                first_boot(self._token_for(ref), cert, key).encode()
            ).decode()
            spec_tags = models.TagSpecification()
            spec_tags.ResourceType, spec_tags.Tags = "instance", tags
            run.TagSpecification = [spec_tags]
            try:
                instance_id = str(self._api().RunInstances(run).InstanceIdSet[0])
            except Exception as exc:  # noqa: BLE001 - try the next zone when this one can't
                if not any(code in str(exc) for code in _ZONE_ERRORS):
                    raise
                logger.warning("zone %s refused a %s: %s", zone, run.InstanceType, exc)
                last = exc
                continue
            with self._addr_lock:
                self._refs[instance_id] = ref
            return instance_id
        raise RuntimeError(f"no zone has a {config.types[spec]} available") from last

    def _describe(self, instance_ids: list[str] | None = None, offset: int = 0) -> list[Any]:
        request = self._models().DescribeInstancesRequest()
        if instance_ids is not None:
            # An id from another provider (an AGS computer made before the switch) is not ours.
            instance_ids = [i for i in instance_ids if i.startswith("ins-")]
            if not instance_ids:
                return []
            request.InstanceIds = instance_ids
        else:
            tag = self._models().Filter()
            tag.Name, tag.Values = "tag-key", [MANAGED_TAG]
            request.Filters = [tag]
            request.Offset, request.Limit = offset, 100
        return list(self._api().DescribeInstances(request).InstanceSet or [])

    def _forget(self, instance_id: str) -> None:
        with self._addr_lock:
            self._addresses.pop(instance_id, None)

    def resume(self, instance_id: str) -> None:
        # A computer still shutting down cannot be started yet.
        deadline = time.monotonic() + 120
        while self._raw_state(instance_id) == "STOPPING" and time.monotonic() < deadline:
            time.sleep(2)
        self._forget(instance_id)
        request = self._models().StartInstancesRequest()
        request.InstanceIds = [instance_id]
        self._api().StartInstances(request)

    def disk_gb(self, instance_id: str) -> int:
        """The system disk, billed by Tencent Cloud for as long as the instance exists."""
        return self._cvm_config.disk_gb

    def pause(self, instance_id: str) -> None:
        self._forget(instance_id)
        request = self._models().StopInstancesRequest()
        request.InstanceIds = [instance_id]
        request.StopType = "SOFT_FIRST"
        request.StoppedMode = "STOP_CHARGING"
        self._api().StopInstances(request)

    def stop(self, instance_id: str) -> None:
        self._forget(instance_id)
        with self._addr_lock:
            self._refs.pop(instance_id, None)
        request = self._models().TerminateInstancesRequest()
        request.InstanceIds = [instance_id]
        self._api().TerminateInstances(request)

    def _raw_state(self, instance_id: str) -> str | None:
        found = self._describe([instance_id])
        return str(found[0].InstanceState) if found else None

    def state(self, instance_id: str) -> State:
        return cvm_state(self._raw_state(instance_id))

    def stopped_at(self, instance_id: str) -> float | None:
        # CVM never stops a computer by itself: only this server pauses or terminates them.
        return None

    def instances(self) -> list[Instance]:
        found: list[Instance] = []
        offset = 0
        while True:
            page = self._describe(offset=offset)
            for item in page:
                labels = {t.Key: t.Value for t in (item.Tags or []) if t.Key}
                found.append(
                    Instance(
                        instance_id=str(item.InstanceId),
                        state=cvm_state(item.InstanceState),
                        labels=labels,
                        created_at=_created(item.CreatedTime),
                    )
                )
            if len(page) < 100:
                return found
            offset += 100

    # -- the way in: the instance's nginx ------------------------------------------

    def _lookup(self, instance_id: str) -> tuple[str, str]:
        with self._addr_lock:
            address, ref = self._addresses.get(instance_id), self._refs.get(instance_id)
        if address and ref:
            return address, ref
        found = self._describe([instance_id])
        if not found:
            raise RuntimeError(f"cloud computer {instance_id} is gone")
        item = found[0]
        ref = next((t.Value for t in (item.Tags or []) if t.Key == REF_TAG), None)
        address = (item.PublicIpAddresses or [None])[0]
        if not ref or not address:
            raise RuntimeError(f"cloud computer {instance_id} has no address yet")
        with self._addr_lock:
            self._addresses[instance_id], self._refs[instance_id] = address, ref
        return address, ref

    def url(self, instance_id: str, port: int, path: str, *, scheme: str = "https") -> str:
        address, _ = self._lookup(instance_id)
        return f"{scheme}://{address}{_GATEWAY.format(port=port)}{path}"

    def token(self, instance_id: str, *, fresh: bool = False) -> str:
        if fresh:
            self._forget(instance_id)
        _, ref = self._lookup(instance_id)
        return self._token_for(ref)

    def ssl_context(self) -> ssl.SSLContext:
        """For the screen relay's WebSocket: trust only this server's instance CA."""
        return self._ca.context()

    def ssl_context_for(self, instance_id: str) -> ssl.SSLContext:
        return self._ca.context()

    def _request(
        self, instance_id: str, path: str, *, timeout: float, method: str = "POST", **kwargs: Any
    ) -> Any:
        if self._http is None:
            import httpx  # noqa: PLC0415

            self._http = httpx.Client(verify=self._ca.context())
        try:
            return super()._request(instance_id, path, timeout=timeout, method=method, **kwargs)
        except Exception:
            # The address may have changed (stopped and started elsewhere): look it up again.
            self._forget(instance_id)
            raise

    def wait_ready(self, instance_id: str, timeout: float = 300.0) -> None:
        """A CVM boots for a minute or more, longer than an AGS resume."""
        super().wait_ready(instance_id, timeout=max(timeout, 300.0))


def _created(value: str | None) -> float:
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()
