"""Binary sensor platform for EntityCraft."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([EntityCraftAlarmSensor(hass.data[DOMAIN][entry.entry_id], entry)])


class EntityCraftAlarmSensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Alarm"
    _attr_icon = "mdi:alert-circle"

    def __init__(self, rule, entry: ConfigEntry) -> None:
        self.rule = rule
        self._attr_unique_id = f"{entry.entry_id}_alarm"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}, "name": entry.title, "manufacturer": "EntityCraft"}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.rule.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self.rule.is_active

    @property
    def extra_state_attributes(self):
        return {"matched_entities": self.rule.matched_entities, "status": self.rule.status}
