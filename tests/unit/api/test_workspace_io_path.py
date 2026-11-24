"""Workspace I/O path resolution for download / file APIs."""

from __future__ import annotations

from pathlib import Path

import pytest

from octop.api.routers.workspace import (
    _assert_workspace_mutable,
    _guard_workspace_read,
    _workspace_io_path,
)
from octop.infra.errors import OctopError


def test_from_workspace_false_slash_is_host_absolute() -> None:
    abs_path = "/Users/jubaoliang/Desktop/IronMan_PPT/钢铁侠.pptx"
    assert _workspace_io_path(abs_path, from_workspace=False) == abs_path
    assert _workspace_io_path("/logo.png", from_workspace=False) == "/logo.png"


def test_from_workspace_true_slash_is_workspace_relative() -> None:
    assert _workspace_io_path("/logo.png", from_workspace=True) == "logo.png"
    assert _workspace_io_path("/outbound/a.pptx", from_workspace=True) == "outbound/a.pptx"
    assert _workspace_io_path("/", from_workspace=True) == "."


def test_relative_without_slash_always_workspace() -> None:
    assert (
        _workspace_io_path("generated/water-ppt/a.pptx", from_workspace=False)
        == "generated/water-ppt/a.pptx"
    )
    assert (
        _workspace_io_path("generated/water-ppt/a.pptx", from_workspace=True)
        == "generated/water-ppt/a.pptx"
    )


def test_file_url_always_host_absolute() -> None:
    assert (
        _workspace_io_path("file:///Users/me/report.pptx", from_workspace=False)
        == "/Users/me/report.pptx"
    )
    assert (
        _workspace_io_path("file:///Users/me/report.pptx", from_workspace=True)
        == "/Users/me/report.pptx"
    )


def test_default_from_workspace_is_false() -> None:
    assert _workspace_io_path("/Users/me/a.pptx") == "/Users/me/a.pptx"


def test_mutable_host_path_stays_inside_workspace() -> None:
    assert _assert_workspace_mutable("/etc/passwd") == "etc/passwd"


def test_mutable_path_rejects_parent_and_file_url() -> None:
    with pytest.raises(OctopError) as parent:
        _assert_workspace_mutable("../octop.db")
    assert parent.value.code.value == "FORBIDDEN"
    with pytest.raises(OctopError):
        _assert_workspace_mutable("file:///etc/passwd")


def test_read_guard_rejects_parent_and_system_root(tmp_path: Path) -> None:
    with pytest.raises(OctopError):
        _guard_workspace_read("outbound/../../etc/passwd", tmp_path, host_files=True)
    with pytest.raises(OctopError):
        _guard_workspace_read("/etc/passwd", tmp_path, host_files=True)


def test_read_guard_per_owner(tmp_path: Path) -> None:
    """Host paths are open to a self-hosted agent; a cloud tenant's are read in its workspace."""
    inside = str(tmp_path / "report.pdf")
    assert _guard_workspace_read(inside, tmp_path, host_files=True) == inside
    assert _guard_workspace_read(inside, tmp_path, host_files=False) == "report.pdf"
    assert _guard_workspace_read("outbound/report.pdf", tmp_path, host_files=False) == (
        "outbound/report.pdf"
    )


def test_a_cloud_tenants_paths_never_leave_its_workspace(tmp_path: Path) -> None:
    """The Bot's ``/`` is its workspace, here or on its cloud computer; the disk is not."""
    read = lambda path: _guard_workspace_read(path, tmp_path, host_files=False)  # noqa: E731
    assert read("/generated/plan.md") == "generated/plan.md"
    assert read("/home/user/workspace/generated/plan.md") == "generated/plan.md"
    assert read("/etc/passwd") == "etc/passwd"
    assert read("/") == "."
    with pytest.raises(OctopError) as escaped:
        read("/generated/../../../etc/passwd")
    assert escaped.value.code.value == "FORBIDDEN"
