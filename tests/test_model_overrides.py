"""Per-model overrides: battery size and the direct-TPMS "check tyres" band."""

from __future__ import annotations

import pytest

from custom_components.carlinko.common.consts import (
    BLOB,
    DEFAULT_BATTERY_KWH,
    DEFAULT_TYRE_PSI_MAX,
    DEFAULT_TYRE_PSI_MIN,
    KNOWN_CAR_OVERRIDES,
    TYRE_INVALID,
    BlobSection,
)
from custom_components.carlinko.models.enrichments import Enrichments
from custom_components.carlinko.models.entity_specs import get_entity_specs
from custom_components.carlinko.models.vehicle_state import VehicleState


def _tyre_blob(raw: tuple[int, int, int, int]) -> bytes:
    """Status blob that is all zero except four raw tyre-pressure bytes."""
    start, end = BLOB["tyres"]
    # Long enough to pass every section gate in Enrichments.apply().
    blob = bytearray(max(end, max(s.value for s in BlobSection) + 1))
    blob[start : start + 4] = bytes(raw)
    return bytes(blob)


def _tyre_status(raw: tuple[int, int, int, int], ctx: dict) -> str | None:
    new_data: dict = {}
    Enrichments(_tyre_blob(raw), new_data, ctx).enrich_tpms()
    return new_data.get("tyre_status")


# Raw 204 at the default 1.373 scale is about 280 kPa = 40.6 psi.
_WARM = (204, 203, 202, 200)


def test_default_band_is_unchanged() -> None:
    assert (DEFAULT_TYRE_PSI_MIN, DEFAULT_TYRE_PSI_MAX) == (28.0, 40.0)
    assert _tyre_status((165, 165, 165, 165), {}) == "normal"  # ~32.9 psi
    assert _tyre_status(_WARM, {}) == "check_tyres"  # one tyre above 40 psi
    assert _tyre_status((120, 165, 165, 165), {}) == "check_tyres"  # ~23.9 psi


def test_band_can_be_set_per_model() -> None:
    ctx = {"tyre_psi_min": 30.0, "tyre_psi_max": 44.0}
    assert _tyre_status(_WARM, ctx) == "normal"
    assert _tyre_status((145, 204, 204, 204), ctx) == "check_tyres"  # ~28.9 psi
    assert _tyre_status((204, 204, 204, 225), ctx) == "check_tyres"  # ~44.8 psi


def test_invalid_tyre_bytes_do_not_set_a_status() -> None:
    assert _tyre_status((TYRE_INVALID,) * 4, {"tyre_psi_max": 44.0}) is None


def test_vehicle_state_passes_model_band_to_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        KNOWN_CAR_OVERRIDES,
        "test band car",
        {"battery_kwh": 50.0, "tyre_psi_min": 30.0, "tyre_psi_max": 44.0},
    )
    blob_hex = _tyre_blob(_WARM).hex()

    plain = VehicleState()
    plain.update_metadata({"vehicle": {"model": "Unknown EV"}})
    assert plain.update_data(blob_hex)["tyre_status"] == "check_tyres"

    banded = VehicleState()
    banded.update_metadata({"vehicle": {"model": "Test Band Car"}})
    assert banded.update_data(blob_hex)["tyre_status"] == "normal"


def test_chery_q_profile_matches_cloud_model_name() -> None:
    state = VehicleState()
    data = state.update_metadata({"vehicle": {"model": "Chery Q"}})
    assert data["battery_kwh"] == 42.7
    assert data["battery_kwh"] != DEFAULT_BATTERY_KWH
    # Door placard 250 kPa (36.3 psi) front and rear: band is -20 % / +20 %.
    assert state._tyre_psi_min == 29.0
    assert state._tyre_psi_max == 43.5


def _chery_q_tyre_status(raw: tuple[int, int, int, int]) -> str:
    state = VehicleState()
    state.update_metadata({"vehicle": {"model": "Chery Q"}})
    return state.update_data(_tyre_blob(raw).hex())["tyre_status"]


def test_chery_q_tyre_band_follows_door_placard() -> None:
    # psi = raw * 1.373 * 0.145038
    assert _chery_q_tyre_status((182, 182, 182, 182)) == "normal"  # placard, 36.2
    assert _chery_q_tyre_status(_WARM) == "normal"  # 39.8-40.6, as first observed
    assert _chery_q_tyre_status((146, 182, 182, 182)) == "normal"  # 29.1
    assert _chery_q_tyre_status((145, 182, 182, 182)) == "check_tyres"  # 28.9
    assert _chery_q_tyre_status((182, 182, 182, 218)) == "normal"  # 43.4
    assert _chery_q_tyre_status((182, 182, 182, 219)) == "check_tyres"  # 43.6


def _fuel_blob() -> str:
    """Status blob (hex) whose fuel-level byte is non-zero, as a PHEV would send."""
    blob = bytearray(_tyre_blob((TYRE_INVALID,) * 4))
    blob[BLOB["fuel_pct"]] = 50
    return blob.hex()


def _spec_keys(state: dict) -> set[str]:
    return {s.key for s in get_entity_specs(state=state, caps={})}


_FUEL_KEYS = {"fuel", "fuel_range", "total_range", "fuel_consumption"}


def test_unknown_model_with_fuel_bytes_is_detected_as_phev() -> None:
    state = VehicleState()
    state.update_metadata({"vehicle": {"model": "Unknown EV"}})
    data = state.update_data(_fuel_blob())
    assert data["powertrain"] == "phev"
    assert _FUEL_KEYS <= _spec_keys(data)


def test_chery_q_never_gets_fuel_sensors() -> None:
    state = VehicleState()
    state.update_metadata({"vehicle": {"model": "Chery Q"}})
    data = state.update_data(_fuel_blob())
    assert data["powertrain"] == "bev"
    assert data["fuel"] is None
    assert not _FUEL_KEYS & _spec_keys(data)


def test_chery_q_profile_does_not_catch_other_models() -> None:
    for model in ("J5", "Chery", "Q5", "EV"):
        state = VehicleState()
        assert state.update_metadata({"vehicle": {"model": model}})[
            "battery_kwh"
        ] != pytest.approx(42.7)
