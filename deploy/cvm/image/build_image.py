"""Build the Octop Bot cloud-computer CVM image: start a builder, run setup.sh, save the image.

Reads OCTOP_CVM_* from the environment (same as the server). Prints the new image id; the
builder instance is always terminated, even when the build fails.

    set -a; . ~/.config/octop-bot/cvm.env; set +a
    uv run python deploy/cvm/image/build_image.py
"""

from __future__ import annotations

import base64
import os
import secrets
import sys
import time
from pathlib import Path

from tencentcloud.common.credential import Credential
from tencentcloud.cvm.v20170312 import cvm_client
from tencentcloud.cvm.v20170312 import models as cm
from tencentcloud.tat.v20201028 import models as tm
from tencentcloud.tat.v20201028 import tat_client

BASE_IMAGE = os.environ.get("OCTOP_CVM_BASE_IMAGE", "img-487zeit5")  # Ubuntu Server 22.04 LTS
ZONE = os.environ.get("OCTOP_CVM_BUILD_ZONE", "ap-guangzhou-6")


def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def main() -> int:
    region = os.environ.get("OCTOP_CVM_REGION", "ap-guangzhou")
    cred = Credential(os.environ["OCTOP_CVM_SECRET_ID"], os.environ["OCTOP_CVM_SECRET_KEY"])
    cvm = cvm_client.CvmClient(cred, region)
    tat = tat_client.TatClient(cred, region)
    subnets = dict(s.split(":", 1) for s in os.environ["OCTOP_CVM_SUBNETS"].split(","))

    run = cm.RunInstancesRequest()
    run.InstanceChargeType = "POSTPAID_BY_HOUR"
    run.InstanceType = os.environ.get("OCTOP_CVM_TYPE", "SA9.LARGE8")
    run.ImageId = BASE_IMAGE
    run.Placement = cm.Placement()
    run.Placement.Zone = ZONE
    run.SystemDisk = cm.SystemDisk()
    run.SystemDisk.DiskType, run.SystemDisk.DiskSize = "CLOUD_BSSD", 40
    run.VirtualPrivateCloud = cm.VirtualPrivateCloud()
    run.VirtualPrivateCloud.VpcId = os.environ["OCTOP_CVM_VPC_ID"]
    run.VirtualPrivateCloud.SubnetId = subnets[ZONE]
    run.SecurityGroupIds = [os.environ["OCTOP_CVM_SECURITY_GROUP"]]
    run.InternetAccessible = cm.InternetAccessible()
    run.InternetAccessible.InternetChargeType = "TRAFFIC_POSTPAID_BY_HOUR"
    run.InternetAccessible.InternetMaxBandwidthOut = 100
    run.InternetAccessible.PublicIpAssigned = True
    run.LoginSettings = cm.LoginSettings()
    # Nobody logs in (no SSH is open); the password only satisfies the API.
    run.LoginSettings.Password = "Oc" + secrets.token_urlsafe(18) + "9!"
    run.InstanceName = "octop-image-builder"
    tag = cm.Tag()
    tag.Key, tag.Value = "octop", "image-builder"
    spec = cm.TagSpecification()
    spec.ResourceType, spec.Tags = "instance", [tag]
    run.TagSpecification = [spec]
    builder = cvm.RunInstances(run).InstanceIdSet[0]
    log(f"builder {builder} starting in {ZONE}")
    try:
        _wait_state(cvm, builder, "RUNNING")
        _wait_agent(tat, builder)
        log("running setup.sh (this takes 10-25 minutes)")
        setup = base64.b64encode((Path(__file__).parent / "setup.sh").read_bytes()).decode()
        # TAT returns only the start of a long output: keep the full log on the builder and
        # return its tail, where any error is.
        script = (
            f"echo {setup} | base64 -d > /root/setup.sh; "
            "bash /root/setup.sh > /root/setup.log 2>&1; rc=$?; tail -80 /root/setup.log; exit $rc"
        )
        command = tm.RunCommandRequest()
        command.Content = base64.b64encode(script.encode()).decode()
        command.InstanceIds = [builder]
        command.CommandType = "SHELL"
        command.Timeout = 3600
        command.Username = "root"
        command.WorkingDirectory = "/root"
        invocation = tat.RunCommand(command).InvocationId
        ok, output = _wait_invocation(tat, invocation)
        if not ok:
            log("setup.sh failed; last output:\n" + output[-4000:])
            return 1
        log("setup done; stopping the builder")
        stop = cm.StopInstancesRequest()
        stop.InstanceIds, stop.StopType = [builder], "SOFT_FIRST"
        cvm.StopInstances(stop)
        _wait_state(cvm, builder, "STOPPED")
        create = cm.CreateImageRequest()
        create.InstanceId = builder
        create.ImageName = "octop-bot-desktop-" + time.strftime("%Y%m%d-%H%M")
        create.ImageDescription = "Octop Bot cloud computer: XFCE, Xvnc, OSWorld desktop server, nginx"
        image = cvm.CreateImage(create).ImageId
        log(f"image {image} creating")
        _wait_image(cvm, image)
        print(image)
        return 0
    finally:
        log(f"terminating builder {builder}")
        end = cm.TerminateInstancesRequest()
        end.InstanceIds = [builder]
        try:
            cvm.TerminateInstances(end)
        except Exception as exc:  # noqa: BLE001 - report and leave it for a manual check
            log(f"could not terminate {builder}: {exc}")


def _wait_state(cvm: cvm_client.CvmClient, instance: str, want: str) -> None:
    for _ in range(120):
        req = cm.DescribeInstancesStatusRequest()
        req.InstanceIds = [instance]
        found = cvm.DescribeInstancesStatus(req).InstanceStatusSet
        state = found[0].InstanceState if found else "?"
        if state == want:
            log(f"{instance} {state}")
            return
        if state == "LAUNCH_FAILED":
            raise RuntimeError(f"{instance} failed to launch")
        time.sleep(5)
    raise TimeoutError(f"{instance} never reached {want}")


def _wait_agent(tat: tat_client.TatClient, instance: str) -> None:
    for _ in range(60):
        req = tm.DescribeAutomationAgentStatusRequest()
        req.InstanceIds = [instance]
        found = tat.DescribeAutomationAgentStatus(req).AutomationAgentSet
        if found and found[0].AgentStatus == "Online":
            log("automation agent online")
            return
        time.sleep(5)
    raise TimeoutError("automation agent never came online")


def _wait_invocation(tat: tat_client.TatClient, invocation: str) -> tuple[bool, str]:
    deadline = time.monotonic() + 3700
    while time.monotonic() < deadline:
        req = tm.DescribeInvocationTasksRequest()
        f = tm.Filter()
        f.Name, f.Values = "invocation-id", [invocation]
        req.Filters, req.HideOutput = [f], False
        tasks = tat.DescribeInvocationTasks(req).InvocationTaskSet
        if tasks and tasks[0].TaskStatus not in ("PENDING", "DELIVERING", "RUNNING", "START"):
            result = tasks[0].TaskResult
            output = base64.b64decode(result.Output or "").decode(errors="replace") if result else ""
            code = result.ExitCode if result else None
            log(f"setup.sh {tasks[0].TaskStatus} (exit {code})")
            return tasks[0].TaskStatus == "SUCCESS" and code == 0, output
        time.sleep(15)
    raise TimeoutError("setup.sh did not finish in time")


def _wait_image(cvm: cvm_client.CvmClient, image: str) -> None:
    for _ in range(240):
        req = cm.DescribeImagesRequest()
        req.ImageIds = [image]
        found = cvm.DescribeImages(req).ImageSet
        state = found[0].ImageState if found else "?"
        if state == "NORMAL":
            log(f"image {image} ready")
            return
        if state in ("CREATEFAILED", "IMPORTFAILED"):
            raise RuntimeError(f"image {image} {state}")
        time.sleep(10)
    raise TimeoutError(f"image {image} never became ready")


if __name__ == "__main__":
    sys.exit(main())
