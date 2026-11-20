"""CarLinko number entities (cost knobs + charge limit)."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common.base_entity import CarlinkoEntity
from .common.consts import CHARGE_LIMIT_OPTIONS
from .common.entity_setup import async_setup_entities
from .common.helpers import partial_id
from .managers.coordinator import CarlinkoCoordinator
from .models.entity_specs import EntitySpec

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

_CHARGE_LIMIT_KEY = "charge_limit"

_LIMITS = {
    "tariff": (0, 1e7, 0.01),
    "petrol_price": (0, 1e7, 0.01),
    "petrol_kml": (0, 100, 0.1),
    # Same anchors as the CarLinko app's charge-limit slider.
    _CHARGE_LIMIT_KEY: (
        min(CHARGE_LIMIT_OPTIONS),
        max(CHARGE_LIMIT_OPTIONS),
        CHARGE_LIMIT_OPTIONS[1] - CHARGE_LIMIT_OPTIONS[0],
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CarlinkoCoordinator = entry.runtime_data
    async_setup_entities(
        hass, entry, coordinator, "number", async_add_entities, CarlinkoNumber
    )


class CarlinkoNumber(CarlinkoEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(
        self, coordinator: CarlinkoCoordinator, spec: EntitySpec, vehicle_id: str
    ) -> None:
        super().__init__(coordinator, spec, vehicle_id)
        lo, hi, step = _LIMITS.get(spec.config_key or spec.key, (0, 1e7, 0.01))
        self._attr_native_min_value = lo
        self._attr_native_max_value = hi
        self._attr_native_step = step
        if spec.key == _CHARGE_LIMIT_KEY:
            self._attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> float | None:
        value = self._state_value()
        if value is None:
            return None
        return float(value)

    async def async_set_native_value(self, value: float) -> None:
        key = self.spec.config_key or self.spec.key
        _LOGGER.debug(
            f"async_set_native_value entity={key} "
            f"vehicle={partial_id(self.vehicle_id)} value={value}"
        )
        if self.spec.key == _CHARGE_LIMIT_KEY:
            # Cloud write; the coordinator validates, reads back and publishes.
            await self.coordinator.async_set_charge_limit(self.vehicle_id, value)
            _LOGGER.debug(f"async_write_ha_state entity={key}")
            self.async_write_ha_state()
            return
        result = self.coordinator.store.set_cost_config(key, value)
        if not result.get("ok"):
            err = result.get("error") or "set failed"
            _LOGGER.warning(f"local config set failed key={key} error={err}")
            raise ValueError(err)
        _LOGGER.info(
            f"local config set key={key} vehicle={partial_id(self.vehicle_id)} "
            f"value={value}"
        )
        await self.coordinator.store.async_save()
        _LOGGER.debug(f"async_write_ha_state entity={key}")
        self.async_write_ha_state()
