"""EntityCraft integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .runtime import EntityCraftRule


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one EntityCraft rule from a config entry."""
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
