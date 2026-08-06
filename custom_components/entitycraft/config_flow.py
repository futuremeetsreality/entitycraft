"""Config flow for EntityCraft."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

DOMAIN = "entitycraft"


class EntityCraftConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial EntityCraft setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Create the single EntityCraft service entry."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title="EntityCraft", data={})

        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))
