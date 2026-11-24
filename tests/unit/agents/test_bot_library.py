"""Bot profile → Library: recency groups and which recorded files are listed."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from octop.infra.agents.bot_library import _collect, period_of
from octop.infra.utils.thread_artifact import ThreadArtifact

TZ = "Asia/Shanghai"
NOW = dt.datetime(2026, 11, 24, 0, 30, tzinfo=ZoneInfo(TZ))


def _at(**delta: float) -> int:
    return int((NOW - dt.timedelta(**delta)).timestamp())


def test_periods_follow_the_server_calendar() -> None:
    assert period_of(_at(minutes=20), timezone=TZ, now=NOW) == "today"
    # 00:10 UTC+8 yesterday is still "yesterday" even though it is under a day ago.
    assert period_of(_at(minutes=40), timezone=TZ, now=NOW) == "week"
    assert period_of(_at(days=6), timezone=TZ, now=NOW) == "week"
    assert period_of(_at(days=7), timezone=TZ, now=NOW) == "older"


def _thread(thread_id: str, at: int, *paths: tuple[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        thread_id=thread_id,
        last_active=at,
        created_at=at,
        artifacts=tuple(ThreadArtifact(path=p, agent_id=a) for p, a in paths),
    )


def test_collect_keeps_this_bots_files_once_newest_thread_first() -> None:
    rows = [
        _thread("new", 20, ("/ws/out/a.pdf", "bot"), ("/Users/me/Desktop/b.key", "bot")),
        _thread("old", 10, ("/ws/out/a.pdf", ""), ("/ws/.octop/plans/p.md", "bot")),
        _thread("room", 5, ("/ws/out/c.txt", "peer")),
    ]
    local = _collect(rows, "bot", ["/ws"], cloud=False)
    assert [(f.path, f.host, f.thread_id) for f in local] == [
        ("/Users/me/Desktop/b.key", True, "new"),
        ("out/a.pdf", False, "new"),
    ]
    # A cloud tenant's Bot sees its workspace as "/": every path it reports is in there.
    cloud = _collect(rows, "bot", ["/ws"], cloud=True)
    assert [(f.path, f.host) for f in cloud] == [
        ("Users/me/Desktop/b.key", False),
        ("out/a.pdf", False),
    ]


def test_a_cloud_bots_files_are_found_in_its_workspace() -> None:
    rows = [
        _thread(
            "t",
            10,
            ("/generated/plan.md", "bot"),
            ("/home/user/workspace/data/table.csv", "bot"),
            ("/data/agents/bot/result.txt", "bot"),
            ("/../etc/passwd", "bot"),
        )
    ]
    found = _collect(rows, "bot", ["/data/agents/bot"], cloud=True)
    assert sorted(f.path for f in found) == ["data/table.csv", "generated/plan.md", "result.txt"]
    assert not any(f.host for f in found)
