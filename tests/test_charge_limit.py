"""Charge limit: REST contract, entity catalog, number entity.

Coordinator read/write tests need the HA plugin and live in ``test_coordinator.py``.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.carlinko.common.consts import API_VERSION, CHARGE_LIMIT_OPTIONS
from custom_components.carlinko.managers.api_client import ApiClient
from custom_components.carlinko.models.entity_specs import (
    ENTITY_SPECS,
    get_entity_specs,
)
from custom_components.carlinko.models.exceptions import AuthError
from custom_components.carlinko.number import CarlinkoNumber
from homeassistant.components.number import NumberMode

# --- REST contract -----------------------------------------------------------


def _api_client() -> ApiClient:
    store = MagicMock()
    store.data = {"token": "tok"}
    client = ApiClient("user@example.com", "secret", "sea", store, MagicMock())
    client.token = "tok"
    client.sign_key = b"0123456789abcdef"
    return client


def _mock_verb(client: ApiClient, verb: str, payload: dict) -> MagicMock:
    response = MagicMock()
    response.status = 200
    response.json = AsyncMock(return_value=payload)
    call = MagicMock(return_value=MagicMock())
    call.return_value.__aenter__ = AsyncMock(return_value=response)
    call.return_value.__aexit__ = AsyncMock(return_value=None)
    setattr(client.session, verb, call)
    return call


def test_charge_limit_options_are_the_app_anchors() -> None:
    assert CHARGE_LIMIT_OPTIONS == (80, 90, 100)


@pytest.mark.asyncio
async def test_get_charge_settings_signs_vehicle_id() -> None:
    client = _api_client()
    get = _mock_verb(
        client, "get", {"code": "0000", "data": {"targetSoc": 90, "lowBattery": 1}}
    )

    data = await client.get_charge_settings("veh-1")

    assert data == {"targetSoc": 90, "lowBattery": 1}
    args, kwargs = get.call_args
    assert args[0].endswith("/user/device/manage/terminalNoticeConfig/veh-1")
    assert "params" not in kwargs
    headers = kwargs["headers"]
    assert headers["version"] == API_VERSION
    assert headers["signature"] == client.sign(
        {"vehicleId": "veh-1", "timestamp": headers["timestamp"]}
    )


@pytest.mark.asyncio
async def test_get_charge_settings_none_on_cloud_error() -> None:
    client = _api_client()
    _mock_verb(client, "get", {"code": "5000", "msg": "nope"})
    assert await client.get_charge_settings("veh-1") is None
    assert await client.get_charge_settings("") is None


@pytest.mark.asyncio
async def test_get_charge_settings_raises_when_token_stays_stale() -> None:
    client = _api_client()
    _mock_verb(client, "get", {"code": "9997"})
    with patch.object(client, "login", new_callable=AsyncMock, return_value="tok2"):
        with pytest.raises(AuthError):
            await client.get_charge_settings("veh-1")


@pytest.mark.asyncio
async def test_set_charge_limit_put_body_and_signature() -> None:
    client = _api_client()
    put = _mock_verb(client, "put", {"code": "0000"})

    result = await client.set_charge_limit("veh-1", 90)

    assert result["code"] == "0000"
    args, kwargs = put.call_args
    assert args[0].endswith("/user/device/manage/targetSoc")
    # Body is the app's ChangeSocParams: the two fields only, no timestamp.
    assert json.loads(kwargs["data"]) == {"targetSoc": 90, "vehicleId": "veh-1"}
    headers = kwargs["headers"]
    assert headers["content-type"] == "application/json"
    assert headers["version"] == API_VERSION
    assert headers["token"] == "tok"
    assert headers["signature"] == client.sign(
        {"targetSoc": 90, "vehicleId": "veh-1", "timestamp": headers["timestamp"]}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [0, 50, 79, 85, 95, 101, 80.5, "90", None, True])
async def test_set_charge_limit_refuses_non_anchor_values(value) -> None:
    client = _api_client()
    put = _mock_verb(client, "put", {"code": "0000"})

    result = await client.set_charge_limit("veh-1", value)

    assert result["code"] == "-1"
    put.assert_not_called()


@pytest.mark.asyncio
async def test_set_charge_limit_requires_vehicle_id() -> None:
    client = _api_client()
    put = _mock_verb(client, "put", {"code": "0000"})
    result = await client.set_charge_limit("", 90)
    assert result["code"] == "-1"
    put.assert_not_called()


@pytest.mark.asyncio
async def test_set_charge_limit_not_in_diagnostics_query_log() -> None:
    client = _api_client()
    _mock_verb(client, "put", {"code": "0000"})
    await client.set_charge_limit("veh-1", 80)
    log = client.query_log_for_diagnostics()
    assert not any("targetSoc" in k for k in log["account"])
    assert not any("targetSoc" in k for b in log["vehicles"].values() for k in b)


# --- Entity catalog ----------------------------------------------------------


def _spec(key: str):
    return next(s for s in ENTITY_SPECS if s.key == key)


def test_charge_limit_entity_only_when_cloud_reports_a_limit() -> None:
    def keys(state: dict) -> set[str]:
        return {s.key for s in get_entity_specs(platform="number", state=state)}

    assert "charge_limit" not in keys({})
    assert "charge_limit" not in keys({"charge_settings": {"target_soc": None}})
    assert "charge_limit" in keys({"charge_settings": {"target_soc": 100}})


# --- Number entity -----------------------------------------------------------


def _entity_coordinator(target_soc: int | None) -> MagicMock:
    coordinator = MagicMock()
    coordinator.store.get_vehicle_meta.return_value = {
        "plate": "P",
        "model": "Chery Q",
        "vin": "V",
    }
    coordinator.vehicle_data.return_value = {
        "vehicle": {"plate": "P", "model": "Chery Q", "vin": "V"},
        "charge_settings": {"target_soc": target_soc},
    }
    coordinator.vehicle_ids = ["veh-1"]
    coordinator.is_available.return_value = False
    coordinator.async_set_charge_limit = AsyncMock(return_value=90)
    return coordinator


@pytest.mark.asyncio
async def test_charge_limit_number_entity() -> None:
    coordinator = _entity_coordinator(100)
    entity = CarlinkoNumber(coordinator, _spec("charge_limit"), "veh-1")
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    assert entity._attr_translation_key == "charge_limit"
    assert entity.unique_id == "carlinko_veh-1_charge_limit"
    assert entity.native_value == 100.0
    assert entity.native_min_value == 80
    assert entity.native_max_value == 100
    assert entity.native_step == 10
    assert entity.mode == NumberMode.SLIDER
    assert entity.native_unit_of_measurement == "%"
    # Saved cloud setting: usable while the car's live stream is down.
    assert entity.available is True

    await entity.async_set_native_value(90.0)

    coordinator.async_set_charge_limit.assert_awaited_once_with("veh-1", 90.0)
    coordinator.store.set_cost_config.assert_not_called()


def test_cost_number_entities_stay_box_mode() -> None:
    coordinator = _entity_coordinator(None)
    coordinator.store.get_cost_config.return_value = {"tariff": 1.0}
    entity = CarlinkoNumber(coordinator, _spec("tariff"), "veh-1")
    assert entity.mode == NumberMode.BOX
