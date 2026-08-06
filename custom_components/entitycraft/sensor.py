"""Sensor platform for EntityCraft."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([EntityCraftStatusSensor(hass.data[DOMAIN][entry.entry_id], entry)])


class EntityCraftStatusSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Status"
    _attr_icon = "mdi:state-machine"

    def __init__(self, rule, entry: ConfigEntry) -> None:
        self.rule = rule
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}, "name": entry.title, "manufacturer": "EntityCraft"}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.rule.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        return self.rule.status

    @property
    def extra_state_attributes(self):
        return {"matched_entities": self.rule.matched_entities, "enabled": self.rule.enabled}
