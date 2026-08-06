"""EntityCraft integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    ACTION_TURN_ON,
    CONF_RESET_ACTION,
    CONF_RESET_TARGET,
    CONF_TRIGGER_ACTION,
    CONF_TRIGGER_TARGET,
    DOMAIN,
    PLATFORMS,
)
from .runtime import EntityCraftRule


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older scene-only rules to generic action targets."""
    if entry.version == 1:
        data = dict(entry.data)
        trigger_scene = data.pop("trigger_scene", None)
        reset_scene = data.pop("reset_scene", None)
        if trigger_scene:
            data[CONF_TRIGGER_TARGET] = {"entity_id": trigger_scene}
            data[CONF_TRIGGER_ACTION] = ACTION_TURN_ON
        if reset_scene:
            data[CONF_RESET_TARGET] = {"entity_id": reset_scene}
            data[CONF_RESET_ACTION] = ACTION_TURN_ON
        hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after changes made with the Configure button."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one EntityCraft rule from a config entry."""
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    rule = EntityCraftRule(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = rule
    await rule.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an EntityCraft rule."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        rule: EntityCraftRule = hass.data[DOMAIN].pop(entry.entry_id)
        await rule.async_stop()
    return unloaded
