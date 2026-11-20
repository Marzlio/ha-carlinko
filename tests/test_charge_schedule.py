"""Scheduled charging: cloud body, signing, and entity catalog.

Coordinator read/write tests need the HA plugin and live in ``test_coordinator.py``.
"""

from __future__ import annotations

from datetime import time
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.carlinko.common.consts import API_VERSION
from custom_components.carlinko.managers.api_client import ApiClient
from custom_components.carlinko.models.charge_schedule import (
    battery_schedule_body,
    parse_battery_schedule,
)
from custom_components.carlinko.models.entity_specs import (
    ENTITY_SPECS,
    get_entity_specs,
)
from custom_components.carlinko.number import CarlinkoNumber
from custom_components.carlinko.switch import CarlinkoSwitch
from custom_components.carlinko.time import CarlinkoTime
from homeassistant.components.number import NumberMode

_MONDAY = [True, False, False, False, False, False, False]
_READY = {
    "schedule_enabled": True,
    "schedule_hour": 22,
    "schedule_minute": 30,
    "schedule_duration": 6,
    "schedule_days": _MONDAY,
}


def _api_client() -> ApiClient:
    store = MagicMock()
    store.data = {"token": "tok"}
    client = ApiClient("user@example.com", "secret", "sea", store, MagicMock())
    client.token = "tok"
    client.sign_key = b"0123456789abcdef"
    return client


def _mock_put(client: ApiClient, payload: dict) -> MagicMock:
    response = MagicMock()
    response.status = 200
    response.json = AsyncMock(return_value=payload)
    call = MagicMock(return_value=MagicMock())
    call.return_value.__aenter__ = AsyncMock(return_value=response)
    call.return_value.__aexit__ = AsyncMock(return_value=None)
    client.session.put = call
    return call


def test_parse_reverses_sunday_first_week_to_monday_first() -> None:
    # Wire order is Sunday → Monday. A true in the last slot is Monday.
    parsed = parse_battery_schedule(
        {
            "enabled": False,
            "hour": 7,
            "minute": 5,
            "duration": 2,
            "week": [False, False, False, False, False, False, True],
        }
    )
    assert parsed == {
        "schedule_enabled": False,
        "schedule_hour": 7,
        "schedule_minute": 5,
        "schedule_duration": 2,
        "schedule_days": _MONDAY,
    }


def test_parse_ignores_a_missing_schedule_object() -> None:
    assert parse_battery_schedule(None) is None
    assert parse_battery_schedule("off") is None


def test_body_reverses_days_and_sends_a_numeric_vehicle_id() -> None:
    body = battery_schedule_body("42", _READY)
    assert body == {
        "duration": 6,
        "enabled": True,
        "hour": 22,
        "minute": 30,
        "vehicleId": 42,
        "week": [False, False, False, False, False, False, True],
    }


def test_body_keeps_a_non_numeric_vehicle_id_as_text() -> None:
    body = battery_schedule_body("veh-1", _READY)
    assert body is not None
    assert body["vehicleId"] == "veh-1"


def test_body_refuses_an_empty_week() -> None:
    settings = dict(_READY)
    settings["schedule_days"] = [False] * 7
    assert battery_schedule_body("42", settings) is None


def test_sign_uses_json_text_for_bools_and_lists() -> None:
    client = _api_client()
    typed = {"enabled": True, "week": [True, False], "timestamp": "5"}
    text = {"enabled": "true", "week": "[true,false]", "timestamp": "5"}
    assert client.sign(typed) == client.sign(text)


@pytest.mark.asyncio
async def test_set_charge_schedule_put_body_and_signature() -> None:
    client = _api_client()
    put = _mock_put(client, {"code": "0000"})

    result = await client.set_charge_schedule("42", _READY)

    assert result["code"] == "0000"
    args, kwargs = put.call_args
    assert args[0].endswith("/user/device/manage/batterySchedule")
    assert json.loads(kwargs["data"]) == {
        "duration": 6,
        "enabled": True,
        "hour": 22,
        "minute": 30,
        "vehicleId": 42,
        "week": [False, False, False, False, False, False, True],
    }
    headers = kwargs["headers"]
    assert headers["content-type"] == "application/json"
    assert headers["version"] == API_VERSION
    assert headers["token"] == "tok"
    body = json.loads(kwargs["data"])
    assert headers["signature"] == client.sign(
        {**body, "timestamp": headers["timestamp"]}
    )


@pytest.mark.asyncio
async def test_set_charge_schedule_refuses_incomplete_without_a_request() -> None:
    client = _api_client()
    put = _mock_put(client, {"code": "0000"})
    result = await client.set_charge_schedule("42", {"schedule_enabled": True})
    assert result["code"] == "-1"
    put.assert_not_called()


@pytest.mark.asyncio
async def test_set_charge_schedule_not_in_diagnostics_query_log() -> None:
    client = _api_client()
    _mock_put(client, {"code": "0000"})
    await client.set_charge_schedule("42", _READY)
    log = client.query_log_for_diagnostics()
    assert not any("batterySchedule" in key for key in log["account"])
    assert not any(
        "batterySchedule" in key
        for bucket in log["vehicles"].values()
        for key in bucket
    )


def test_schedule_entities_follow_the_charge_limit() -> None:
    def keys(state: dict) -> set[str]:
        return {spec.key for spec in get_entity_specs(state=state)}

    assert "charge_schedule" not in keys({})
    present = keys({"charge_settings": {"target_soc": 80}})
    assert "charge_schedule" in present
    assert "charge_schedule_time" in present
    assert "charge_schedule_duration" in present
    assert "charge_schedule_mon" in present
    assert "charge_schedule_sun" in present


def _entity_coordinator(settings: dict) -> MagicMock:
    coordinator = MagicMock()
    coordinator.store.get_vehicle_meta.return_value = {
        "plate": "P",
        "model": "Chery Q",
        "vin": "V",
    }
    coordinator.vehicle_data.return_value = {
        "vehicle": {"plate": "P", "model": "Chery Q", "vin": "V"},
        "charge_settings": settings,
    }
    coordinator.vehicle_ids = ["veh-1"]
    coordinator.async_set_charge_schedule = AsyncMock(return_value={})
    return coordinator


def _bind(entity):
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    return entity


def _spec(key: str):
    return next(spec for spec in ENTITY_SPECS if spec.key == key)


@pytest.mark.asyncio
async def test_schedule_time_entity_reads_and_writes_the_clock() -> None:
    coordinator = _entity_coordinator(
        {"schedule_hour": 22, "schedule_minute": 30, "target_soc": 80}
    )
    entity = _bind(CarlinkoTime(coordinator, _spec("charge_schedule_time"), "veh-1"))
    assert entity.native_value == time(22, 30)
    await entity.async_set_value(time(6, 15))
    coordinator.async_set_charge_schedule.assert_awaited_once_with(
        "veh-1", hour=6, minute=15
    )


@pytest.mark.asyncio
async def test_schedule_switch_and_duration_call_the_coordinator() -> None:
    coordinator = _entity_coordinator(
        {"schedule_enabled": False, "schedule_days": _MONDAY, "schedule_duration": 4}
    )
    switch = _bind(CarlinkoSwitch(coordinator, _spec("charge_schedule"), "veh-1"))
    monday = _bind(CarlinkoSwitch(coordinator, _spec("charge_schedule_mon"), "veh-1"))
    duration = _bind(
        CarlinkoNumber(coordinator, _spec("charge_schedule_duration"), "veh-1")
    )
    assert switch.is_on is False
    assert monday.is_on is True
    assert duration.native_value == 4
    assert duration.mode == NumberMode.SLIDER
    await switch.async_turn_on()
    await monday.async_turn_off()
    await duration.async_set_native_value(8)
    assert coordinator.async_set_charge_schedule.await_args_list[0].kwargs == {
        "enabled": True
    }
    assert coordinator.async_set_charge_schedule.await_args_list[1].kwargs == {
        "day_index": 0,
        "day_on": False,
    }
    assert coordinator.async_set_charge_schedule.await_args_list[2].kwargs == {
        "duration": 8
    }
