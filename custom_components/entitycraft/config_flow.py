"""Config and options flows for EntityCraft."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    ACTION_RESTORE_PREVIOUS,
    ACTION_TOGGLE,
    ACTION_TURN_OFF,
    ACTION_TURN_ON,
    CONF_ACTIVE_STATE,
    CONF_DELAY,
    CONF_ENTITIES,
    CONF_LOGIC,
    CONF_RESET_ACTION,
    CONF_RESET_DELAY,
    CONF_RESET_TARGET,
    CONF_TRIGGER_ACTION,
    CONF_TRIGGER_TARGET,
    DOMAIN,
    LOGIC_ALL,
    LOGIC_ANY,
)


def _schema(defaults: dict | None = None) -> vol.Schema:
    """Build the rule form schema."""
    defaults = defaults or {}
    trigger_actions = [ACTION_TURN_ON, ACTION_TURN_OFF, ACTION_TOGGLE]
    reset_actions = [
        ACTION_RESTORE_PREVIOUS,
        ACTION_TURN_ON,
        ACTION_TURN_OFF,
        ACTION_TOGGLE,
    ]
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            vol.Required(CONF_ENTITIES, default=defaults.get(CONF_ENTITIES, [])): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Required(CONF_LOGIC, default=defaults.get(CONF_LOGIC, LOGIC_ANY)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[LOGIC_ANY, LOGIC_ALL], mode=selector.SelectSelectorMode.DROPDOWN, translation_key="logic")
            ),
            vol.Required(CONF_ACTIVE_STATE, default=defaults.get(CONF_ACTIVE_STATE, "on")): selector.SelectSelector(
                selector.SelectSelectorConfig(options=["on", "off"], mode=selector.SelectSelectorMode.DROPDOWN, translation_key="active_state")
            ),
            vol.Required(CONF_DELAY, default=defaults.get(CONF_DELAY, 0)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=3600, step=1, unit_of_measurement="s")
            ),
            vol.Required(CONF_TRIGGER_TARGET, default=defaults.get(CONF_TRIGGER_TARGET, {})): selector.TargetSelector(),
            vol.Required(CONF_TRIGGER_ACTION, default=defaults.get(CONF_TRIGGER_ACTION, ACTION_TURN_ON)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=trigger_actions, mode=selector.SelectSelectorMode.DROPDOWN, translation_key="action")
            ),
            vol.Required(CONF_RESET_DELAY, default=defaults.get(CONF_RESET_DELAY, 0)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=3600, step=1, unit_of_measurement="s")
            ),
            vol.Required(CONF_RESET_TARGET, default=defaults.get(CONF_RESET_TARGET, defaults.get(CONF_TRIGGER_TARGET, {}))): selector.TargetSelector(),
            vol.Required(CONF_RESET_ACTION, default=defaults.get(CONF_RESET_ACTION, ACTION_RESTORE_PREVIOUS)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=reset_actions, mode=selector.SelectSelectorMode.DROPDOWN, translation_key="action")
            ),
        }
    )


class EntityCraftConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create one EntityCraft rule per config entry."""

    VERSION = 2

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Return the options flow used by the visible Configure button."""
        return EntityCraftOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema())

    async def async_step_reconfigure(self, user_input: dict | None = None) -> FlowResult:
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            self.hass.config_entries.async_update_entry(entry, title=user_input[CONF_NAME], data=user_input)
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reconfigure_successful")
        defaults = {**entry.data, **entry.options, CONF_NAME: entry.title}
        return self.async_show_form(step_id="reconfigure", data_schema=_schema(defaults))


class EntityCraftOptionsFlow(config_entries.OptionsFlow):
    """Edit an EntityCraft rule through the Configure button."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        defaults = {**self.config_entry.data, **self.config_entry.options, CONF_NAME: self.config_entry.title}
        return self.async_show_form(step_id="init", data_schema=_schema(defaults))
