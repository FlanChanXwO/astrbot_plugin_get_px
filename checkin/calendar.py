"""Check-in calendar view-model, event collection and self-contained template.

This module feeds the ``签到日历 [YYYY-MM]`` T2I image card. The visual
contract lives in ``templates/checkin_calendar/DESIGN_BRIEF.md`` (v1 定稿版);
any template, style or field change must bump ``CALENDAR_TEMPLATE_VERSION`` so
stale cache images are re-rendered.
"""

from __future__ import annotations

import base64
import calendar
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from html import escape
from pathlib import Path
import re
from typing import Callable, Sequence

from lunar_python import Solar

from .models import CheckinRecord

CHECKIN_CALENDAR_WIDTH = 1600
CHECKIN_CALENDAR_HEIGHT = 900
CALENDAR_TEMPLATE_VERSION = "calendar:1"
CALENDAR_EVENT_LIMIT = 6

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "checkin_calendar"
_FONT_PATH = (
    Path(__file__).resolve().parent.parent
    / "templates"
    / "checkin_themes"
    / "default"
    / "fonts"
    / "LXGWWenKaiLite-GB2312.woff2"
)
_CSS_MARKER = "/*__CHECKIN_CALENDAR_CSS__*/"
_FONT_DATA_MARKER = "__CHECKIN_CALENDAR_FONT_DATA__"

_ZeroArgLookup = Callable[[str], object | None]


@dataclass(frozen=True)
class CalendarEvent:
    """A raw month event before normalization (solar term, lunar or custom)."""

    start: str
    end: str
    name: str
    is_off_day: bool = True


def _validate_month(month: str) -> date:
    raw = str(month or "")
    if re.fullmatch(r"\d{4}-\d{2}", raw) is None:
        raise ValueError("month must use YYYY-MM")
    try:
        return date.fromisoformat(f"{raw}-01")
    except ValueError as exc:
        raise ValueError("month must use YYYY-MM") from exc


def _validate_today_key(today_key: str) -> str:
    raw = str(today_key or "")
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("today_key must use YYYY-MM-DD") from exc
    if parsed.isoformat() != raw:
        raise ValueError("today_key must use YYYY-MM-DD")
    return raw


def collect_calendar_events(
    *,
    month: str,
    holiday_lookup: _ZeroArgLookup | None,
    custom_events: Sequence[object] = (),
) -> list[CalendarEvent]:
    """Gather a month's raw events from lunar_python, holidays and customs.

    ``holiday_lookup`` maps an ISO date to an object with ``name`` and
    ``is_off_day`` attributes (``checkin.holiday.HolidayCalendar.lookup``),
    or is ``None`` when the calendar is unavailable. ``custom_events`` items
    are ``CheckinGlobalEvent``-like objects with ``date_value``
    (``MM-DD`` annual or ``YYYY-MM-DD`` once) and ``name``.
    """
    start = _validate_month(month)
    year, month_num = start.year, start.month
    events: list[CalendarEvent] = []
    seen: set[tuple[str, str]] = set()
    for day_num in range(1, calendar.monthrange(year, month_num)[1] + 1):
        day = date(year, month_num, day_num)
        day_key = day.isoformat()
        lunar = Solar.fromYmd(year, month_num, day_num).getLunar()
        for name in (lunar.getJieQi(), *lunar.getFestivals()):
            if name and (day_key, name) not in seen:
                seen.add((day_key, name))
                events.append(CalendarEvent(day_key, day_key, name))
        if holiday_lookup is not None:
            holiday = holiday_lookup(day_key)
            if holiday is not None and getattr(holiday, "name", ""):
                events.append(
                    CalendarEvent(
                        day_key,
                        day_key,
                        str(holiday.name),
                        bool(getattr(holiday, "is_off_day", True)),
                    )
                )
    for item in custom_events:
        date_value = str(getattr(item, "date_value", "") or "")
        name = str(getattr(item, "name", "") or "").strip()
        if not name:
            continue
        day_key = _custom_event_date(date_value, year, month_num)
        if day_key and (day_key, name) not in seen:
            seen.add((day_key, name))
            events.append(CalendarEvent(day_key, day_key, name))
    return events


def _custom_event_date(date_value: str, year: int, month_num: int) -> str:
    """Map annual MM-DD / once YYYY-MM-DD to an ISO date inside the target month."""
    raw = date_value.strip()
    month_prefix = f"{year}-{month_num:02d}"
    if len(raw) == 5 and raw[2] == "-":  # annual MM-DD
        candidate = f"{year}-{raw}"
        return candidate if candidate.startswith(month_prefix) else ""
    try:
        date.fromisoformat(raw)
    except ValueError:
        return ""
    return raw if raw.startswith(month_prefix) else ""


def _coerce_event(item: CalendarEvent | dict) -> CalendarEvent:
    if isinstance(item, CalendarEvent):
        return item
    if isinstance(item, dict):
        return CalendarEvent(
            start=str(item.get("start") or ""),
            end=str(item.get("end") or item.get("start") or ""),
            name=str(item.get("name") or ""),
            is_off_day=bool(item.get("is_off_day", True)),
        )
    raise TypeError("calendar event must be a CalendarEvent or dict")


def summarize_calendar_events(
    events: Sequence[CalendarEvent | dict], *, month: str, today_key: str
) -> tuple[list[dict], int]:
    """Normalize raw events into visible chips and a folded-count.

    Rules (contract): workday adjustments (``is_off_day=False``) are dropped;
    same-name events fold into one shown on the earliest day; the current
    month only shows events that have not started, historical months keep
    all; results are sorted by date and truncated to ``CALENDAR_EVENT_LIMIT``.
    """
    valid = [_coerce_event(item) for item in events]
    valid = [item for item in valid if item.is_off_day and item.name]
    merged: dict[str, dict] = {}
    for item in sorted(valid, key=lambda e: e.start):
        slot = merged.setdefault(
            item.name,
            {"start": item.start, "end": item.end, "name": item.name},
        )
        slot["start"] = min(slot["start"], item.start)
        slot["end"] = max(slot["end"], item.end)
    current = month == today_key[:7]
    visible = [
        item
        for item in merged.values()
        if not current or item["start"] >= today_key
    ]
    visible.sort(key=lambda item: item["start"])
    shown = [
        {"day": int(item["start"][8:10]), "name": item["name"]}
        for item in visible[:CALENDAR_EVENT_LIMIT]
    ]
    return shown, max(0, len(visible) - CALENDAR_EVENT_LIMIT)


def build_checkin_calendar_data(
    *,
    month: str,
    today_key: str,
    records: Sequence[CheckinRecord],
    background_url: str = "",
    background_credit: str = "",
    events: Sequence[CalendarEvent | dict] = (),
) -> dict:
    """Build the Jinja2 view-model consumed by the calendar template."""
    start = _validate_month(month)
    _validate_today_key(today_key)
    year, month_num = start.year, start.month
    record_by_date = {
        record.date_key: record
        for record in records
        if record.date_key.startswith(f"{month}-")
    }
    checked_days = len(record_by_date)
    coins_earned = sum(int(record.coins_reward) for record in record_by_date.values())
    weeks: list[list[dict]] = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month_num):
        row: list[dict] = []
        for day in week:
            key = day.isoformat()
            if day.month != month_num:
                row.append(
                    {
                        "day": "",
                        "date_key": "",
                        "state": "outside",
                        "state_label": "",
                        "coins_label": "",
                    }
                )
                continue
            if key in record_by_date:
                state, label, coins = (
                    "checked",
                    "已签到",
                    f"+{int(record_by_date[key].coins_reward)}",
                )
            elif key > today_key:
                state, label, coins = "future", "未到", "—"
            else:
                state, label, coins = "missed", "未签到", "—"
            row.append(
                {
                    "day": day.day,
                    "date_key": key,
                    "state": state,
                    "state_label": label,
                    "coins_label": coins,
                }
            )
        weeks.append(row)
    while len(weeks) < 6:
        weeks.append(
            [
                {
                    "day": "",
                    "date_key": "",
                    "state": "outside",
                    "state_label": "",
                    "coins_label": "",
                }
                for _ in range(7)
            ]
        )
    shown_events, hidden = summarize_calendar_events(
        tuple(events), month=month, today_key=today_key
    )
    return {
        "month_label": escape(f"{year} 年 {month_num:02d} 月"),
        "checked_days": checked_days,
        "coins_earned": coins_earned,
        "as_of_date": escape(today_key),
        "today_key": escape(today_key),
        "empty": checked_days == 0,
        "background_url": escape(str(background_url or "")),
        "background_credit": escape(str(background_credit or "")),
        "events": shown_events,
        "events_hidden_count": hidden,
        "weeks": weeks,
    }


@lru_cache(maxsize=1)
def get_checkin_calendar_template() -> str:
    """Assemble the self-contained calendar HTML with inlined CSS and font."""
    html = (_TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")
    css = (_TEMPLATE_DIR / "style.css").read_text(encoding="utf-8")
    if _CSS_MARKER not in html:
        raise RuntimeError("check-in calendar template is missing its CSS marker")
    if _FONT_DATA_MARKER not in css:
        raise RuntimeError("check-in calendar style is missing its font marker")
    font_data = base64.b64encode(_FONT_PATH.read_bytes()).decode("ascii")
    css = css.replace(_FONT_DATA_MARKER, font_data)
    return html.replace(_CSS_MARKER, css)