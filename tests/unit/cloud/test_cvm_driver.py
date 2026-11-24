"""Cloud computers on Tencent Cloud CVM: lifecycle, the per-instance way in, provider choice."""

from __future__ import annotations

import base64
import re
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException

from octop.infra.cloud.computers import manager as computers
from octop.infra.cloud.computers.cvm import (
    MANAGED_TAG,
    REF_TAG,
    CvmConfig,
    CvmDriver,
    InstanceCA,
    cvm_state,
)
from octop.infra.cloud.computers.driver import AgsDriver
from octop.infra.cloud.computers.mixed import MixedDriver

ENV = {
    "OCTOP_CVM_SECRET_ID": "AKID-test",
    "OCTOP_CVM_SECRET_KEY": "secret-test",
    "OCTOP_CVM_IMAGE_ID": "img-octop",
    "OCTOP_CVM_VPC_ID": "vpc-1",
    "OCTOP_CVM_SUBNETS": "ap-guangzhou-6:subnet-6, ap-guangzhou-7:subnet-7",
    "OCTOP_CVM_SECURITY_GROUP": "sg-1",
}


class FakeCvm:
    """Records CVM calls; ``sold_out`` zones refuse RunInstances like a stock shortage."""

    def __init__(self) -> None:
        self.runs: list[Any] = []
        self.calls: list[tuple[str, Any]] = []
        self.sold_out: set[str] = set()
        self.instances: dict[str, Any] = {}

    def RunInstances(self, req: Any) -> Any:  # noqa: N802 - SDK method name
        self.runs.append(req)
        if req.Placement.Zone in self.sold_out:
            raise TencentCloudSDKException("ResourceInsufficient.SpecifiedInstanceType", "sold out")
        instance_id = f"ins-{len(self.runs)}"
        self.instances[instance_id] = SimpleNamespace(
            InstanceId=instance_id,
            InstanceState="RUNNING",
            Tags=req.TagSpecification[0].Tags,
            PublicIpAddresses=["203.0.113.7"],
            CreatedTime="2026-11-24T07:00:00Z",
        )
        return SimpleNamespace(InstanceIdSet=[instance_id])

    def DescribeInstances(self, req: Any) -> Any:  # noqa: N802
        ids = req.InstanceIds or list(self.instances)
        return SimpleNamespace(InstanceSet=[self.instances[i] for i in ids if i in self.instances])

    def StopInstances(self, req: Any) -> Any:  # noqa: N802
        self.calls.append(("stop", req))
        for i in req.InstanceIds:
            self.instances[i].InstanceState = "STOPPED"
            self.instances[i].PublicIpAddresses = []
        return SimpleNamespace()

    def StartInstances(self, req: Any) -> Any:  # noqa: N802
        self.calls.append(("start", req))
        for i in req.InstanceIds:
            self.instances[i].InstanceState = "RUNNING"
            self.instances[i].PublicIpAddresses = ["198.51.100.9"]
        return SimpleNamespace()

    def TerminateInstances(self, req: Any) -> Any:  # noqa: N802
        self.calls.append(("terminate", req))
        for i in req.InstanceIds:
            self.instances.pop(i, None)
        return SimpleNamespace()


@pytest.fixture
def cvm() -> tuple[CvmDriver, FakeCvm]:
    config = CvmConfig.from_env(ENV)
    assert config is not None
    driver = CvmDriver(config)
    fake = FakeCvm()
    driver._client = fake
    return driver, fake


def _user_data(req: Any) -> str:
    return base64.b64decode(req.UserData).decode()


def test_config_needs_the_network_and_image() -> None:
    assert CvmConfig.from_env({}) is None
    assert CvmConfig.from_env({k: v for k, v in ENV.items() if k != "OCTOP_CVM_IMAGE_ID"}) is None
    config = CvmConfig.from_env(ENV)
    assert config is not None
    assert config.subnets == (("ap-guangzhou-6", "subnet-6"), ("ap-guangzhou-7", "subnet-7"))
    assert dict(config.types) == {"standard": "SA9.LARGE8", "pro": "SA9.2XLARGE16"}
    assert config.region == "ap-guangzhou"


def test_states_map_a_stopped_computer_to_paused() -> None:
    assert cvm_state("RUNNING") == "running"
    assert cvm_state("PENDING") == "starting"
    assert cvm_state("STOPPED") == cvm_state("STOPPING") == "paused"
    assert cvm_state("SHUTDOWN") == cvm_state("LAUNCH_FAILED") == cvm_state(None) == "gone"


def test_start_tags_the_computer_and_hands_it_its_own_token_and_certificate(cvm: Any) -> None:
    driver, fake = cvm
    instance = driver.start(spec="standard", labels={"octop-bot": "bot-a", "octop-user": "7"})
    run = fake.runs[0]
    assert run.InstanceType == "SA9.LARGE8" and run.ImageId == "img-octop"
    assert run.InstanceChargeType == "POSTPAID_BY_HOUR"
    assert run.SecurityGroupIds == ["sg-1"] and run.VirtualPrivateCloud.SubnetId == "subnet-6"
    tags = {t.Key: t.Value for t in run.TagSpecification[0].Tags}
    assert tags["octop-bot"] == "bot-a" and tags[MANAGED_TAG] == "1" and len(tags[REF_TAG]) == 32

    data = _user_data(run)
    token = re.search(r"printf %s (\w+) > /etc/octop/token", data)
    assert token and token.group(1) == driver.token(instance)
    assert "STOP_CHARGING" not in data and "nginx" in data
    cert_b64 = re.search(r"echo (\S+) \| base64 -d > /etc/octop/cert.pem", data)
    assert cert_b64
    cert = x509.load_pem_x509_certificate(base64.b64decode(cert_b64.group(1)))
    # Issued by the CA every server with the same CAM secret derives.
    other = CvmDriver(CvmConfig.from_env(ENV))  # type: ignore[arg-type]
    ca_key = other._ca.cert.public_key()
    assert isinstance(ca_key, ec.EllipticCurvePublicKey)
    cert.verify_directly_issued_by(other._ca.cert)
    assert driver.url(instance, 5000, "/execute") == "https://203.0.113.7/p/5000/execute"


def test_a_zone_without_stock_falls_through_to_the_next(cvm: Any) -> None:
    driver, fake = cvm
    fake.sold_out = {"ap-guangzhou-6"}
    driver.start(spec="pro", labels={})
    assert [r.Placement.Zone for r in fake.runs] == ["ap-guangzhou-6", "ap-guangzhou-7"]
    assert fake.runs[-1].InstanceType == "SA9.2XLARGE16"
    fake.sold_out = {"ap-guangzhou-6", "ap-guangzhou-7"}
    with pytest.raises(RuntimeError, match="no zone"):
        driver.start(spec="standard", labels={})


def test_pause_stops_charging_and_resume_finds_the_new_address(cvm: Any) -> None:
    driver, fake = cvm
    instance = driver.start(spec="standard", labels={})
    token = driver.token(instance)
    driver.pause(instance)
    stop = fake.calls[-1][1]
    assert stop.StoppedMode == "STOP_CHARGING" and stop.StopType == "SOFT_FIRST"
    assert driver.state(instance) == "paused"
    driver.resume(instance)
    assert fake.calls[-1][0] == "start" and driver.state(instance) == "running"
    # A stopped computer gets a new public IP; the token stays.
    assert driver.url(instance, 8080, "/websockify", scheme="wss") == (
        "wss://198.51.100.9/p/8080/websockify"
    )
    assert driver.token(instance) == token
    driver.stop(instance)
    assert fake.calls[-1][0] == "terminate" and driver.state(instance) == "gone"


def test_instances_lists_only_octop_computers_with_their_labels(cvm: Any) -> None:
    driver, _fake = cvm
    instance = driver.start(spec="standard", labels={"octop-server": "srv-1"})
    [found] = driver.instances()
    assert found.instance_id == instance and found.state == "running"
    assert found.labels["octop-server"] == "srv-1"
    assert driver.stopped_at(instance) is None


def test_the_instance_ca_trusts_only_its_own_certificates() -> None:
    ca = InstanceCA(b"\x01" * 32)
    cert_pem, _key = ca.issue("octop-computer-x")
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    cert.verify_directly_issued_by(ca.cert)
    stranger = InstanceCA(b"\x02" * 32)
    with pytest.raises(Exception):  # noqa: B017 - any signature failure
        cert.verify_directly_issued_by(stranger.cert)
    assert ca.context().check_hostname is False


def test_provider_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        *ENV,
        "OCTOP_COMPUTER_PROVIDER",
        "OCTOP_AGS_SECRET_ID",
        "OCTOP_AGS_SECRET_KEY",
        "OCTOP_AGS_TOOL",
    ]:
        monkeypatch.delenv(key, raising=False)
    assert computers.computer_driver() is None
    monkeypatch.setenv("OCTOP_AGS_SECRET_ID", "a")
    monkeypatch.setenv("OCTOP_AGS_SECRET_KEY", "b")
    monkeypatch.setenv("OCTOP_AGS_TOOL", "osworld")
    assert type(computers.computer_driver()) is AgsDriver
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    # Both configured: new computers on CVM, earlier AGS computers stay on AGS.
    assert isinstance(computers.computer_driver(), MixedDriver)
    monkeypatch.setenv("OCTOP_COMPUTER_PROVIDER", "cvm")
    assert isinstance(computers.computer_driver(), CvmDriver)
    monkeypatch.setenv("OCTOP_COMPUTER_PROVIDER", "ags")
    assert type(computers.computer_driver()) is AgsDriver
    monkeypatch.setenv("OCTOP_COMPUTER_PROVIDER", "cvm")
    for key in ENV:
        monkeypatch.delenv(key)
    assert computers.computer_driver() is None


class Recorder:
    """Stands in for one provider; records the calls it gets."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, attr: str) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((attr, args))
            return f"{self.name}:{attr}"

        return call


def test_mixed_routes_each_computer_to_the_provider_that_made_it(cvm: Any) -> None:
    cvm_driver, _fake = cvm
    ags = Recorder("ags")
    mixed = MixedDriver(cvm_driver, ags)  # type: ignore[arg-type]
    new = mixed.start(spec="standard", labels={})
    assert new.startswith("ins-")
    mixed.run("old-ags-instance", "ls", 30)
    mixed.pause("old-ags-instance")
    assert [c[0] for c in ags.calls] == ["run", "pause"]
    assert mixed.state(new) == "running"
    assert mixed.state("old-ags-instance") == "ags:state"
    assert mixed.ssl_context_for("old-ags-instance") is None
    assert mixed.ssl_context_for(new) is not None
    # The CVM side never asks Tencent Cloud about another provider's id.
    assert cvm_driver.state("old-ags-instance") == "gone"


def test_only_cvm_computers_have_a_billed_disk(cvm: Any) -> None:
    cvm_driver, _fake = cvm
    ags = Recorder("ags")
    mixed = MixedDriver(cvm_driver, ags)  # type: ignore[arg-type]
    new = mixed.start(spec="standard", labels={})
    assert mixed.disk_gb(new) == 40
    mixed.disk_gb("old-ags-instance")
    assert ags.calls[-1][0] == "disk_gb"
    assert AgsDriver(config=None).disk_gb("old-ags-instance") == 0  # type: ignore[arg-type]
