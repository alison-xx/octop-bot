"""A Bot's scheduled tasks as one-line schedules, soonest first (Bot profile → Activity)."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Sequence
from typing import Any
from zoneinfo import ZoneInfo

from octop.i18n import tr
from octop.infra.cron.trigger import build_trigger
from octop.infra.errors import OctopError

_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_UNIX = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
_EVERY = re.compile(r"(?:\*|0)/(\d+)")
_RANGE = re.compile(r"(\d{1,2})-(\d{1,2})")


def _unix_day(token: str) -> int:
    return int(token) if token.isdigit() else _UNIX[token.lower()]


def _weekdays(field: str) -> tuple[int, ...] | None:
    """Monday-first day numbers for a crontab weekday field, ``None`` when unreadable."""
    if field == "*":
        return tuple(range(7))
    days: set[int] = set()
    try:
        for item in field.split(","):
            first, _, last = item.partition("-")
            start = _unix_day(first)
            end = _unix_day(last) if last else start
            if last and end == 0:
                end = 7
            if not 0 <= start <= end <= 7:
                return None
            days.update((n - 1) % 7 for n in range(start, end + 1))
    except (KeyError, ValueError):
        return None
    return tuple(sorted(days))


def _clock(hour: int, minute: int) -> str:
    return f"{hour}:{minute:02d}"


def _every(seconds: int, locale: str) -> str:
    for unit, size in (("days", 86400), ("hours", 3600), ("minutes", 60)):
        if seconds % size == 0:
            count = seconds // size
            if count == 1:
                return tr(f"cron.schedule.every_{unit[:-1]}", locale)
            return tr(f"cron.schedule.every_{unit}", locale, count=count)
    return tr("cron.schedule.every_seconds", locale, count=seconds)


def _with_days(days: tuple[int, ...], what: str, locale: str, *, daily_key: str) -> str:
    if len(days) == 7:
        return tr(daily_key, locale, what=what)
    if days == (0, 1, 2, 3, 4):
        return tr("cron.schedule.weekdays", locale, what=what)
    if days == (5, 6):
        return tr("cron.schedule.weekends", locale, what=what)
    names = [tr(f"cron.schedule.day.{_DAYS[d]}", locale) for d in days]
    if len(names) == 1:
        return tr("cron.schedule.weekly", locale, day=names[0], what=what)
    return tr(
        "cron.schedule.days", locale, days=tr("cron.schedule.join", locale).join(names), what=what
    )


def _describe_cron(expression: str, locale: str) -> str | None:
    fields = expression.split()
    if len(fields) != 5 or fields[2] != "*" or fields[3] != "*":
        return None
    minute, hour, days_field = fields[0], fields[1], fields[4]
    days = _weekdays(days_field)
    if days is None or not days:
        return None
    if minute.isdigit() and int(minute) < 60:
        m = int(minute)
        hours = hour.split(",")
        if all(h.isdigit() and int(h) < 24 for h in hours):
            times = tr("cron.schedule.join", locale).join(_clock(int(h), m) for h in hours)
            return _with_days(days, times, locale, daily_key="cron.schedule.daily")
        if hour == "*":
            what = tr("cron.schedule.hourly_at", locale, minute=f"{m:02d}")
            return _with_days(days, what, locale, daily_key="cron.schedule.any_day")
        every = _EVERY.fullmatch(hour)
        if every and int(every.group(1)) > 0:
            what = _every(int(every.group(1)) * 3600, locale)
            return _with_days(days, what, locale, daily_key="cron.schedule.any_day")
        return None
    step = _EVERY.fullmatch(minute)
    if minute == "*":
        step_minutes = 1
    elif step and 0 < int(step.group(1)) < 60:
        step_minutes = int(step.group(1))
    else:
        return None
    what = _every(step_minutes * 60, locale)
    window = _RANGE.fullmatch(hour)
    if window:
        start, end = int(window.group(1)), int(window.group(2))
        if not start <= end < 24:
            return None
        what = tr(
            "cron.schedule.window",
            locale,
            every=what,
            start=_clock(start, 0),
            end=_clock(end, (59 // step_minutes) * step_minutes),
        )
    elif hour != "*":
        return None
    return _with_days(days, what, locale, daily_key="cron.schedule.any_day")


def describe_trigger(
    trigger: str, locale: str, *, timezone: str, now: dt.datetime | None = None
) -> str:
    """One line for a schedule (``Weekdays 8:50``), read in the server timezone."""
    kind, _, value = trigger.partition(":")
    value = value.strip()
    text: str | None = None
    if kind == "cron":
        text = _describe_cron(value, locale)
    elif kind == "interval" and value.isdigit() and int(value) > 0:
        text = _every(int(value), locale)
    elif kind == "agently":
        text = tr("cron.schedule.mail", locale)
    elif kind == "date":
        zone = ZoneInfo(timezone)
        try:
            run_at = dt.datetime.fromisoformat(value)
        except ValueError:
            run_at = None
        if run_at is not None:
            run_at = (
                run_at.replace(tzinfo=zone) if run_at.tzinfo is None else run_at.astimezone(zone)
            )
            year = (now or dt.datetime.now(zone)).astimezone(zone).year
            date = tr(
                "cron.schedule.date" if run_at.year == year else "cron.schedule.date_year",
                locale,
                year=run_at.year,
                month=run_at.month,
                day=run_at.day,
                time=_clock(run_at.hour, run_at.minute),
            )
            text = tr("cron.schedule.once", locale, date=date)
    return text or tr("cron.schedule.custom", locale)


def _computed_next_run(trigger: str, timezone: str, now: dt.datetime) -> dt.datetime | None:
    if not trigger.startswith(("cron:", "date:")):
        return None
    try:
        built = build_trigger(trigger, timezone=timezone)
    except OctopError:
        return None
    fire = getattr(built, "get_next_fire_time", None)
    when = fire(None, now) if fire is not None else None
    # A date trigger answers with its run date even after it has passed.
    return when if isinstance(when, dt.datetime) and when >= now else None


def upcoming_jobs(
    rows: Sequence[Any],
    *,
    next_run: Callable[[str], dt.datetime | None],
    locale: str,
    timezone: str,
    now: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    """Enabled jobs soonest first, then enabled jobs with no clock time, then paused ones."""
    current = now or dt.datetime.now(ZoneInfo(timezone))
    items: list[dict[str, Any]] = []
    for row in rows:
        enabled = bool(row.enabled)
        when = None
        if enabled:
            when = next_run(row.cron_id) or _computed_next_run(row.trigger, timezone, current)
        past_once = (
            not enabled
            and row.trigger.startswith("date:")
            and (_computed_next_run(row.trigger, timezone, current) is None)
        )
        items.append(
            {
                "id": row.cron_id,
                "name": row.name,
                "enabled": enabled,
                "trigger": row.trigger,
                "schedule": describe_trigger(row.trigger, locale, timezone=timezone, now=current),
                "next_run_at": int(when.timestamp()) if when is not None else None,
                "can_toggle": row.task_type != "script" and not past_once,
            }
        )
    items.sort(
        key=lambda item: (
            0
            if item["enabled"] and item["next_run_at"] is not None
            else 1
            if item["enabled"]
            else 2,
            item["next_run_at"] or 0,
            item["name"].casefold(),
        )
    )
    return items


__all__ = ["describe_trigger", "upcoming_jobs"]
