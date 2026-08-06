"""Config flow for EntityCraft."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_ACTIVE_STATE,
    CONF_DELAY,
    CONF_ENTITIES,
    CONF_LOGIC,
    CONF_RESET_DELAY,
    CONF_RESET_SCENE,
    CONF_TRIGGER_SCENE,
    DOMAIN,
    LOGIC_ALL,
    LOGIC_ANY,
)


class EntityCraftConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create one EntityCraft rule per config entry."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Create a binary-sensor rule."""
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_ENTITIES): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
                ),
                vol.Required(CONF_LOGIC, default=LOGIC_ANY): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[LOGIC_ANY, LOGIC_ALL],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="logic",
                    )
                ),
                vol.Required(CONF_ACTIVE_STATE, default="on"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["on", "off"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="active_state",
                    )
                ),
                vol.Required(CONF_DELAY, default=0): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=3600, step=1, unit_of_measurement="s")
                ),
                vol.Required(CONF_TRIGGER_SCENE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="scene")
                ),
                vol.Required(CONF_RESET_DELAY, default=0): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=3600, step=1, unit_of_measurement="s")
                ),
                vol.Required(CONF_RESET_SCENE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="scene")
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
