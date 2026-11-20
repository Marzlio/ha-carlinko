"""Cloud charge-schedule body for PUT /user/device/manage/batterySchedule.

The CarLinko app's schedule screen lists days Monday → Sunday, then reverses
that list before the request. The JSON ``week`` array is therefore Sunday →
Monday. This module keeps Home Assistant state in Monday → Sunday order and
reverses it only on the wire. No homeassistant imports.
"""

from __future__ import annotations

from typing import Any

from ..common.consts import CHARGE_SCHEDULE_DAY_KEYS

SCHEDULE_STATE_KEYS = (
    "schedule_enabled",
    "schedule_hour",
    "schedule_minute",
    "schedule_duration",
    "schedule_days",
)


def _whole_number(value: Any, low: int, high: int) -> int | None:
    if isinstance(value, bool) or isinstance(value, str):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    if not isinstance(value, int):
        return None
    if value < low or value > high:
        return None
    return value


def days_from_api_week(week: Any) -> list[bool] | None:
    """API week (Sunday first) → Monday-first booleans, or None if unusable."""
    if not isinstance(week, list) or len(week) != len(CHARGE_SCHEDULE_DAY_KEYS):
        return None
    flags: list[bool] = []
    for item in week:
        if isinstance(item, bool):
            flags.append(item)
        elif item in (0, 1) and not isinstance(item, bool):
            flags.append(bool(item))
        else:
            return None
    return list(reversed(flags))


def api_week_from_days(days: list[bool]) -> list[bool]:
    """Monday-first booleans → the Sunday-first array the cloud stores."""
    return list(reversed(days))


def parse_battery_schedule(raw: Any) -> dict[str, Any] | None:
    """Map a ``batterySchedule`` object onto coordinator state fields.

    Returns None when the cloud did not send an object. A present object may
    still leave individual fields empty when a value is the wrong type.
    """
    if not isinstance(raw, dict):
        return None
    enabled = raw.get("enabled")
    duration = raw.get("duration")
    return {
        "schedule_enabled": enabled if isinstance(enabled, bool) else None,
        "schedule_hour": _whole_number(raw.get("hour"), 0, 23),
        "schedule_minute": _whole_number(raw.get("minute"), 0, 59),
        "schedule_duration": _whole_number(duration, 1, 168),
        "schedule_days": days_from_api_week(raw.get("week")),
    }


def schedule_is_ready(settings: dict[str, Any]) -> bool:
    """True when a cloud write has time, duration, enabled, and one weekday."""
    enabled = settings.get("schedule_enabled")
    hour = settings.get("schedule_hour")
    minute = settings.get("schedule_minute")
    duration = settings.get("schedule_duration")
    days = settings.get("schedule_days")
    if not isinstance(enabled, bool):
        return False
    if _whole_number(hour, 0, 23) is None or _whole_number(minute, 0, 59) is None:
        return False
    if _whole_number(duration, 1, 168) is None:
        return False
    if not isinstance(days, list) or len(days) != len(CHARGE_SCHEDULE_DAY_KEYS):
        return False
    if not all(isinstance(day, bool) for day in days):
        return False
    return any(days)


def battery_schedule_body(
    vehicle_id: str, settings: dict[str, Any]
) -> dict[str, Any] | None:
    """JSON body for the cloud schedule write, or None when it is not ready."""
    if not schedule_is_ready(settings):
        return None
    vid = str(vehicle_id or "").strip()
    if not vid:
        return None
    vehicle_value: int | str = int(vid) if vid.isdigit() and len(vid) <= 15 else vid
    duration = _whole_number(settings.get("schedule_duration"), 1, 168)
    hour = _whole_number(settings.get("schedule_hour"), 0, 23)
    minute = _whole_number(settings.get("schedule_minute"), 0, 59)
    if duration is None or hour is None or minute is None:
        return None
    return {
        "duration": duration,
        "enabled": bool(settings["schedule_enabled"]),
        "hour": hour,
        "minute": minute,
        "vehicleId": vehicle_value,
        "week": api_week_from_days(list(settings["schedule_days"])),
    }
