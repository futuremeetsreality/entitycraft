"""Runtime for an EntityCraft rule."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ACTION_RESTORE_PREVIOUS,
    CONF_ACTIVE_STATE,
    CONF_DELAY,
    CONF_ENTITIES,
    CONF_LOGIC,
    CONF_RESET_ACTION,
    CONF_RESET_DELAY,
    CONF_RESET_TARGET,
    CONF_TRIGGER_ACTION,
    CONF_TRIGGER_TARGET,
    LOGIC_ALL,
)


class EntityCraftRule:
    """Evaluate one portable rule bound to local HA entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.enabled = True
        self.is_active = False
        self.status = "ready"
        self.matched_entities: list[str] = []
        self._delay_task: asyncio.Task | None = None
        self._listeners: list[Callable[[], None]] = []
        self._remove_listener: Callable[[], None] | None = None
        self._snapshot_scene = f"entitycraft_{entry.entry_id.lower()}"

    @property
    def config(self) -> dict:
        """Return effective configuration, with UI options overriding data."""
        return {**self.entry.data, **self.entry.options}

    async def async_start(self) -> None:
        """Start listening for entity changes."""
        self._remove_listener = async_track_state_change_event(
            self.hass, self.config[CONF_ENTITIES], self._handle_state_change
        )
        await self.async_evaluate()

    async def async_stop(self) -> None:
        """Stop the rule."""
        if self._remove_listener:
            self._remove_listener()
        self._cancel_delay()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def _handle_state_change(self, event: Event) -> None:
        self.hass.async_create_task(self.async_evaluate())

    def _condition_matches(self) -> bool:
        config = self.config
        expected = config[CONF_ACTIVE_STATE]
        results: list[bool] = []
        matched: list[str] = []
        for entity_id in config[CONF_ENTITIES]:
            state = self.hass.states.get(entity_id)
            match = state is not None and state.state == expected
            results.append(match)
            if match:
                matched.append(entity_id)
        self.matched_entities = matched
        return all(results) if config[CONF_LOGIC] == LOGIC_ALL else any(results)

    async def async_evaluate(self) -> None:
        """Evaluate current states and transition if necessary."""
        if not self.enabled:
            self.status = "disabled"
            self._cancel_delay()
            self._notify()
            return

        config = self.config
        should_activate = self._condition_matches()
        if should_activate == self.is_active:
            self.status = "active" if self.is_active else "ready"
            self._cancel_delay()
            self._notify()
            return

        delay = float(config[CONF_DELAY] if should_activate else config[CONF_RESET_DELAY])
        self._cancel_delay()
        if delay <= 0:
            await self._apply_state(should_activate)
            return

        self.status = "trigger_wait" if should_activate else "reset_wait"
        self._notify()
        self._delay_task = self.hass.async_create_task(
            self._delayed_transition(should_activate, delay)
        )

    async def _delayed_transition(self, target: bool, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            if self.enabled and self._condition_matches() == target:
                await self._apply_state(target)
        except asyncio.CancelledError:
            return

    @staticmethod
    def _target_entity_ids(target: dict) -> list[str]:
        value = target.get("entity_id", [])
        if isinstance(value, str):
            return [value]
        return list(value)

    async def _apply_state(self, active: bool) -> None:
        config = self.config
        self.is_active = active
        self.status = "active" if active else "ready"

        if active:
            target = config[CONF_TRIGGER_TARGET]
            entity_ids = self._target_entity_ids(target)
            if entity_ids:
                await self.hass.services.async_call(
                    "scene",
                    "create",
                    {
                        "scene_id": self._snapshot_scene,
                        "snapshot_entities": entity_ids,
                    },
                    blocking=True,
                )
            await self.hass.services.async_call(
                "homeassistant",
                config[CONF_TRIGGER_ACTION],
                {},
                target=target,
                blocking=True,
            )
        elif config[CONF_RESET_ACTION] == ACTION_RESTORE_PREVIOUS:
            await self.hass.services.async_call(
                "scene",
                "turn_on",
                {},
                target={"entity_id": f"scene.{self._snapshot_scene}"},
                blocking=True,
            )
        else:
            await self.hass.services.async_call(
                "homeassistant",
                config[CONF_RESET_ACTION],
                {},
                target=config[CONF_RESET_TARGET],
                blocking=True,
            )

        self._notify()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        await self.async_evaluate()

    def _cancel_delay(self) -> None:
        if self._delay_task and not self._delay_task.done():
            self._delay_task.cancel()
        self._delay_task = None
