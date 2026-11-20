"""CarLinko switches."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common.base_entity import CarlinkoEntity
from .common.consts import CHARGE_SCHEDULE_DAY_KEYS
from .common.entity_setup import async_setup_entities
from .managers.coordinator import CarlinkoCoordinator
from .models.entity_specs import EntitySpec

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CarlinkoCoordinator = entry.runtime_data
    async_setup_entities(
        hass, entry, coordinator, "switch", async_add_entities, CarlinkoSwitch
    )


class CarlinkoSwitch(CarlinkoEntity, SwitchEntity):
    def __init__(
        self, coordinator: CarlinkoCoordinator, spec: EntitySpec, vehicle_id: str
    ) -> None:
        super().__init__(coordinator, spec, vehicle_id)

    @property
    def is_on(self) -> bool | None:
        value = self._state_value()
        if value is None:
            # Fall back to related binary paths for command-only switches.
            state = self.coordinator.vehicle_data(self.vehicle_id)
            if self.spec.key == "engine":
                return bool(state.get("engine_on"))
            if self.spec.key == "defrost_cmd":
                return bool(state.get("defrost_front"))
            if self.spec.key == "purify":
                return bool(state.get("purify"))
            return None
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("on", "true", "1")

    def _schedule_day_index(self) -> int | None:
        prefix = "charge_schedule_"
        if not self.spec.key.startswith(prefix):
            return None
        day = self.spec.key[len(prefix) :]
        if day not in CHARGE_SCHEDULE_DAY_KEYS:
            return None
        return CHARGE_SCHEDULE_DAY_KEYS.index(day)

    async def _async_set_schedule(self, **changes) -> None:
        await self.coordinator.async_set_charge_schedule(self.vehicle_id, **changes)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        if self.spec.key == "charge_schedule":
            await self._async_set_schedule(enabled=True)
            return
        day_index = self._schedule_day_index()
        if day_index is not None:
            await self._async_set_schedule(day_index=day_index, day_on=True)
            return
        await self._async_send_action("on")

    async def async_turn_off(self, **kwargs) -> None:
        if self.spec.key == "charge_schedule":
            await self._async_set_schedule(enabled=False)
            return
        day_index = self._schedule_day_index()
        if day_index is not None:
            await self._async_set_schedule(day_index=day_index, day_on=False)
            return
        await self._async_send_action("off")
