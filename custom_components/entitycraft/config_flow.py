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
    BINDING_KEYS,
    CONF_ACTIVE_STATE,
    CONF_DELAY,
    CONF_ENTITIES,
    CONF_LOGIC,
    CONF_RESET_ACTION,
    CONF_RESET_DELAY,
    CONF_RESET_TARGET,
    CONF_SNAPSHOT_ENTITIES,
    CONF_SUSPEND_WHEN,
    CONF_TRIGGER_ACTION,
    CONF_TRIGGER_TARGET,
    CONF_UNAVAILABLE_POLICY,
    DOMAIN,
    LOGIC_ALL,
    LOGIC_ANY,
    UNAVAILABLE_ACTIVATE,
    UNAVAILABLE_HOLD,
)


def _schema(defaults: dict | None = None) -> vol.Schema:
    """Build the rule form schema."""
    defaults = defaults or {}
    trigger_actions = [ACTION_TURN_ON, ACTION_TURN_OFF, ACTION_TOGGLE]
    reset_actions = [ACTION_RESTORE_PREVIOUS, ACTION_TURN_ON, ACTION_TURN_OFF, ACTION_TOGGLE]
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            vol.Required(CONF_ENTITIES, default=defaults.get(CONF_ENTITIES, [])): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Required(CONF_UNAVAILABLE_POLICY, default=defaults.get(CONF_UNAVAILABLE_POLICY, UNAVAILABLE_HOLD)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[UNAVAILABLE_HOLD, UNAVAILABLE_ACTIVATE], mode=selector.SelectSelectorMode.DROPDOWN, translation_key="unavailable_policy")
            ),
            vol.Optional(CONF_SUSPEND_WHEN, default=defaults.get(CONF_SUSPEND_WHEN, [])): selector.EntitySelector(
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
            vol.Optional(CONF_SNAPSHOT_ENTITIES, default=defaults.get(CONF_SNAPSHOT_ENTITIES, [])): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
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

    VERSION = 3

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return EntityCraftOptionsFlow()

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors = _validate(user_input)
        if user_input is not None and not errors:
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema(user_input), errors=errors)

    async def async_step_reconfigure(self, user_input: dict | None = None) -> FlowResult:
        entry = self._get_reconfigure_entry()
        errors = _validate(user_input)
        errors.update(_validate_change(self.hass, entry, user_input))
        if user_input is not None and not errors:
            self.hass.config_entries.async_update_entry(entry, title=user_input[CONF_NAME], data=user_input, options={})
            # The registered update listener performs the one required reload.
            return self.async_abort(reason="reconfigure_successful")
        defaults = {**entry.data, **entry.options, CONF_NAME: entry.title}
        return self.async_show_form(step_id="reconfigure", data_schema=_schema(user_input or defaults), errors=errors)


class EntityCraftOptionsFlow(config_entries.OptionsFlow):
    """Edit an EntityCraft rule through the Configure button."""

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        errors = _validate(user_input)
        errors.update(_validate_change(self.hass, self.config_entry, user_input))
        if user_input is not None and not errors:
            return self.async_create_entry(title="", data=user_input)
        defaults = {**self.config_entry.data, **self.config_entry.options, CONF_NAME: self.config_entry.title}
        return self.async_show_form(step_id="init", data_schema=_schema(user_input or defaults), errors=errors)


def _validate(user_input: dict | None) -> dict[str, str]:
    if user_input is None:
        return {}
    if not user_input.get(CONF_ENTITIES):
        return {CONF_ENTITIES: "no_sensors"}
    if user_input.get(CONF_RESET_ACTION) == ACTION_RESTORE_PREVIOUS:
        explicit = user_input.get(CONF_SNAPSHOT_ENTITIES)
        ids = explicit or user_input.get(CONF_TRIGGER_TARGET, {}).get("entity_id", [])
        if isinstance(ids, str):
            ids = [ids]
        if (not ids or all(entity_id.startswith("scene.") for entity_id in ids)
                or (explicit and any(entity_id.startswith("scene.") for entity_id in ids))):
            return {CONF_SNAPSHOT_ENTITIES: "no_snapshot_entities"}
    return {}


def _validate_change(hass, entry, user_input: dict | None) -> dict[str, str]:
    if user_input is None:
        return {}
    rule = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if rule is not None and rule.is_active:
        if any(user_input.get(key) != rule.config.get(key) for key in BINDING_KEYS):
            return {"base": "alarm_active"}
    return {}
