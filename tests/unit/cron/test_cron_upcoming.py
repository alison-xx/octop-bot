"""Bot profile → Activity: one-line schedules and the upcoming order."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from octop.infra.cron.upcoming import describe_trigger, upcoming_jobs

TZ = "Asia/Shanghai"
NOW = dt.datetime(2026, 11, 24, 7, 0, tzinfo=ZoneInfo(TZ))


@pytest.mark.parametrize(
    ("trigger", "zh", "en"),
    [
        ("cron:50 8 * * 1-5", "工作日 8:50", "Weekdays, 8:50"),
        ("cron:50 8 * * mon-fri", "工作日 8:50", "Weekdays, 8:50"),
        ("cron:0 9 * * *", "每天 9:00", "Daily at 9:00"),
        ("cron:0 9,18 * * *", "每天 9:00、18:00", "Daily at 9:00, 18:00"),
        ("cron:30 10 * * 0,6", "周末 10:30", "Weekends, 10:30"),
        ("cron:0 20 * * sun", "每周日 20:00", "Sundays, 20:00"),
        ("cron:0 8 * * 1,3", "周一、周三 8:00", "Monday, Wednesday, 8:00"),
        ("cron:*/15 8-18 * * *", "每 15 分钟，8:00 – 18:45", "Every 15 min, 8:00 – 18:45"),
        ("cron:*/15 8-18 * * 1-5", "工作日 每 15 分钟，8:00 – 18:45", None),
        ("cron:5 * * * *", "每小时 :05", "Hourly at :05"),
        ("cron:0 */2 * * *", "每 2 小时", "Every 2 hours"),
        ("cron:0 0 1 * *", "自定义", "Custom"),
        ("interval:900", "每 15 分钟", "Every 15 min"),
        ("interval:3600", "每小时", "Every hour"),
        ("interval:172800", "每 2 天", "Every 2 days"),
        ("date:2026-11-30T09:05:00", "一次 · 11月30日 9:05", "Once · 11/30 9:05"),
        ("date:2027-01-02T09:05:00", "一次 · 2027年1月2日 9:05", "Once · 1/2/2027 9:05"),
        ("agently:inbox-1", "收到新邮件时", "When new mail arrives"),
        ("bogus:1", "自定义", "Custom"),
    ],
)
def test_describe_trigger(trigger: str, zh: str, en: str | None) -> None:
    assert describe_trigger(trigger, "zh", timezone=TZ, now=NOW) == zh
    if en is not None:
        assert describe_trigger(trigger, "en", timezone=TZ, now=NOW) == en


def test_once_reads_in_the_server_timezone() -> None:
    text = describe_trigger("date:2026-11-30T01:05:00+00:00", "zh", timezone=TZ, now=NOW)
    assert text == "一次 · 11月30日 9:05"


def _row(cron_id: str, trigger: str, *, enabled: bool = True, task_type: str = "agent"):
    return SimpleNamespace(
        cron_id=cron_id, name=cron_id, trigger=trigger, enabled=enabled, task_type=task_type
    )


def test_upcoming_sorts_by_next_run_then_paused() -> None:
    rows = [
        _row("paused", "cron:0 7 * * *", enabled=False),
        _row("later", "cron:0 20 * * *"),
        _row("mail", "agently:inbox"),
        _row("soon", "cron:30 7 * * *"),
        _row("script", "cron:0 8 * * *", task_type="script"),
        _row("missed", "date:2026-11-01T09:00:00", enabled=False),
    ]
    scheduled = {"later": NOW.replace(hour=20)}
    jobs = upcoming_jobs(rows, next_run=scheduled.get, locale="en", timezone=TZ, now=NOW)

    assert [job["id"] for job in jobs] == ["soon", "script", "later", "mail", "missed", "paused"]
    by_id = {job["id"]: job for job in jobs}
    assert by_id["soon"]["next_run_at"] == int(NOW.replace(minute=30).timestamp())
    assert by_id["later"]["next_run_at"] == int(NOW.replace(hour=20).timestamp())
    assert by_id["mail"]["next_run_at"] is None
    assert by_id["paused"]["next_run_at"] is None and by_id["paused"]["can_toggle"]
    assert not by_id["script"]["can_toggle"]
    assert not by_id["missed"]["can_toggle"]
    assert by_id["soon"]["schedule"] == "Daily at 7:30"
