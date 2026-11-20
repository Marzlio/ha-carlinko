"""CarLinko time entities (scheduled charging start)."""

from __future__ import annotations

from datetime import time
import logging

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common.base_entity import CarlinkoEntity
from .common.entity_setup import async_setup_entities
from .common.helpers import partial_id
from .managers.coordinator import CarlinkoCoordinator
from .models.entity_specs import EntitySpec

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CarlinkoCoordinator = entry.runtime_data
    async_setup_entities(
        hass, entry, coordinator, "time", async_add_entities, CarlinkoTime
    )


class CarlinkoTime(CarlinkoEntity, TimeEntity):
    def __init__(
        self, coordinator: CarlinkoCoordinator, spec: EntitySpec, vehicle_id: str
    ) -> None:
        super().__init__(coordinator, spec, vehicle_id)

    @property
    def native_value(self) -> time | None:
        state = self.coordinator.vehicle_data(self.vehicle_id)
        settings = state.get("charge_settings") if isinstance(state, dict) else None
        if not isinstance(settings, dict):
            return None
        hour = settings.get("schedule_hour")
        minute = settings.get("schedule_minute")
        if not isinstance(hour, int) or not isinstance(minute, int):
            return None
        if isinstance(hour, bool) or isinstance(minute, bool):
            return None
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        return time(hour, minute)

    async def async_set_value(self, value: time) -> None:
        _LOGGER.debug(
            f"async_set_value entity={self.spec.key} "
            f"vehicle={partial_id(self.vehicle_id)} "
            f"hour={value.hour} minute={value.minute}"
        )
        await self.coordinator.async_set_charge_schedule(
            self.vehicle_id, hour=value.hour, minute=value.minute
        )
        self.async_write_ha_state()
