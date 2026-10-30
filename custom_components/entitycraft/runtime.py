"""Runtime for an EntityCraft rule."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager
from copy import deepcopy

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    ACTION_RESTORE_PREVIOUS,
    ACTION_TOGGLE,
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
    UNAVAILABLE_ACTIVATE,
    UNAVAILABLE_HOLD,
)

_LOGGER = logging.getLogger(__name__)
RETRY_DELAY = 5
RESTORE_TIMEOUT = 10
RESTORE_POLL_INTERVAL = 0.1
RESTORE_STABLE_TIME = 0.3


class RuleSuspended(Exception):
    """A higher-priority indicator currently owns the output."""


class EntityCraftRule:
    """Evaluate one portable rule bound to local HA entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        # A config-entry update mutates entry before the old runtime is unloaded.
        # In-flight commands must finish with the configuration they started with.
        self._config = deepcopy({**entry.data, **entry.options})
        self.enabled = True
        self.is_active = False
        self.status = "ready"
        self.matched_entities: list[str] = []
        self.unavailable_entities: list[str] = []
        self.suspended_by: list[str] = []
        self.last_error: str | None = None
        self._blocked_error: str | None = None
        self._toggle_pending = False
        self._restoring = False
        self._transition_lock = asyncio.Lock()
        # Rules sharing explicit output entities serialize commands. Locks are
        # ordered so partially overlapping output sets cannot deadlock.
        output_ids = set(self._snapshot_entity_ids())
        for key in (CONF_TRIGGER_TARGET, CONF_RESET_TARGET):
            output_ids.update(self._target_entity_ids(self.config.get(key, {})))
        locks = hass.data.setdefault(f"{DOMAIN}_output_locks", {})
        self._output_locks = [locks.setdefault(entity_id, asyncio.Lock())
                              for entity_id in sorted(output_ids)]
        self._stopped = False
        self._snapshot_taken = False
        self._saved_states: dict | None = None
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}", atomic_writes=True)
        self._activation_complete = False
        self._delay_task: asyncio.Task | None = None
        self._delay_target: bool | None = None
        self._retry_task: asyncio.Task | None = None
        self._listeners: list[Callable[[], None]] = []
        self._remove_listener: Callable[[], None] | None = None
        self._snapshot_scene = f"entitycraft_{entry.entry_id.lower()}"

    @property
    def config(self) -> dict:
        return self._config

    async def async_start(self) -> None:
        saved = await self._store.async_load()
        if saved:
            try:
                self._load_saved_state(saved)
            except (TypeError, ValueError) as err:
                self.is_active = True
                self._blocked_error = str(err)
        self._remove_listener = async_track_state_change_event(
            self.hass, list(dict.fromkeys(
                self.config[CONF_ENTITIES] + self.config.get(CONF_SUSPEND_WHEN, [])
            )), self._handle_state_change
        )
        await self.async_evaluate()

    def _binding(self) -> dict:
        """Fields that may not change while an earlier alarm owns a snapshot."""
        return {key: self.config.get(key) for key in BINDING_KEYS}

    def _load_saved_state(self, saved: dict) -> None:
        if not isinstance(saved, dict) or type(saved.get("active")) is not bool:
            raise ValueError("Invalid recovery data; manual recovery required")
        self.enabled = saved.get("enabled", True)
        if type(self.enabled) is not bool:
            raise ValueError("Invalid saved enable state; manual recovery required")
        self.is_active = saved["active"]
        if not self.is_active:
            return
        if saved.get("toggle_pending"):
            raise ValueError("Interrupted toggle has an unknown outcome; manual recovery required")
        if saved.get("binding") != self._binding():
            raise ValueError("Rule bindings changed during an alarm; restore the previous configuration")
        snapshot = saved.get("snapshot")
        if self.config[CONF_RESET_ACTION] == ACTION_RESTORE_PREVIOUS:
            if not isinstance(snapshot, dict) or set(snapshot) != set(self._snapshot_entity_ids()):
                raise ValueError("Original snapshot is missing or incomplete; manual recovery required")
            for state in snapshot.values():
                if not isinstance(state, dict) or not isinstance(state.get("state"), str):
                    raise ValueError("Invalid original state; manual recovery required")
                if state["state"] in ("unknown", "unavailable"):
                    raise ValueError("Original state was unavailable; manual recovery required")
        self._saved_states = snapshot
        self._snapshot_taken = bool(snapshot)
        self._activation_complete = self.config[CONF_TRIGGER_ACTION] == ACTION_TOGGLE

    async def async_stop(self) -> None:
        self._stopped = True
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        self._cancel_delay()
        self._cancel_retry()
        # Let a command already sent finish; cancellation can leave the device
        # changed without recording whether the transition completed.
        async with self._transition_lock:
            pass

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
        if not self._stopped:
            self.hass.async_create_task(self.async_evaluate())

    def _condition_matches(self) -> bool:
        config = self.config
        expected = config[CONF_ACTIVE_STATE]
        results: list[bool] = []
        matched: list[str] = []
        unavailable: list[str] = []
        for entity_id in config[CONF_ENTITIES]:
            state = self.hass.states.get(entity_id)
            if state is None or state.state not in ("on", "off"):
                unavailable.append(entity_id)
            match = state is not None and state.state == expected
            results.append(match)
            if match:
                matched.append(entity_id)
        self.matched_entities = matched
        self.unavailable_entities = unavailable
        # Unknown inputs never clear an existing alarm. Generic rules hold;
        # safety indicators may explicitly activate on unknown inputs as well.
        if unavailable or not results:
            return self.is_active or self.config.get(
                CONF_UNAVAILABLE_POLICY, UNAVAILABLE_HOLD
            ) == UNAVAILABLE_ACTIVATE
        return all(results) if config[CONF_LOGIC] == LOGIC_ALL else any(results)

    async def async_evaluate(self) -> None:
        # Every decision AND its awaited services share the same lock.
        async with self._locked_transition():
            await self._evaluate_locked()

    @asynccontextmanager
    async def _locked_transition(self):
        async with self._transition_lock:
            async with AsyncExitStack() as stack:
                for lock in self._output_locks:
                    await stack.enter_async_context(lock)
                yield

    def _is_suspended(self) -> bool:
        """Only confirmed-off guards release a lower-priority rule."""
        self.suspended_by = [
            entity_id for entity_id in self.config.get(CONF_SUSPEND_WHEN, [])
            if (state := self.hass.states.get(entity_id)) is None or state.state != "off"
        ]
        return bool(self.suspended_by)

    def _show_suspended(self) -> None:
        if self.is_active and self.config[CONF_TRIGGER_ACTION] != ACTION_TOGGLE:
            # The higher-priority rule may restore a state reported before our
            # previous command reached the device. Reassert an ongoing activity
            # on resume, keeping its original; never replay a toggle.
            self._activation_complete = False
        self.status = "suspended"
        self._cancel_delay()
        self._cancel_retry()
        self._notify()

    async def _evaluate_locked(self) -> None:
        if self._stopped:
            return
        if not self.enabled:
            self.status = "disabled"
            self._cancel_delay()
            self._cancel_retry()
            self._notify()
            return

        if self._blocked_error or not self.config[CONF_ENTITIES]:
            self.last_error = self._blocked_error or "No monitored sensors configured"
            self.status = "error"
            self._cancel_delay()
            self._cancel_retry()
            self._notify()
            return

        while not self._stopped and self.enabled:
            config = self.config
            should_activate = self._condition_matches()
            if self._is_suspended():
                # Keep any original snapshot, but neither capture an alarm
                # color nor restore over the higher-priority warning.
                self._show_suspended()
                return
            if self._restoring and should_activate:
                # A failed/partial restoration might already have changed the
                # lamp. Reassert the alarm, retaining the same original.
                self._activation_complete = False
            if should_activate == self.is_active and (
                not should_activate or self._activation_complete
            ):
                self.status = (
                    "error" if self.last_error else
                    "input_unavailable" if self.unavailable_entities
                    else "active" if self.is_active else "ready"
                )
                self._cancel_delay()
                self._notify()
                return

            delay = float(config[CONF_DELAY] if should_activate else config[CONF_RESET_DELAY])
            if self._delay_task and self._delay_target == should_activate:
                # Attribute updates and a second open door must not restart an
                # already running delay for the same aggregate condition.
                self._notify()
                return
            self._cancel_delay()
            if delay > 0:
                self.status = "trigger_wait" if should_activate else "reset_wait"
                self._delay_target = should_activate
                self._delay_task = self.hass.async_create_task(
                    self._delayed_transition(should_activate, delay)
                )
                self._notify()
                return
            if not await self._try_apply_state(should_activate):
                return
            # Sensor events may arrive while a service is awaited. Re-read the
            # current inputs before deciding that the transition is finished.

    async def _delayed_transition(self, target: bool, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            async with self._locked_transition():
                if self._delay_task is not asyncio.current_task():
                    return
                # Detach the timer before sending any device commands. New
                # events can cancel waiting timers, never in-flight commands.
                self._delay_task = None
                self._delay_target = None
                if self._stopped or not self.enabled:
                    return
                if self._is_suspended():
                    self._show_suspended()
                    return
                if self._condition_matches() == target:
                    if not await self._try_apply_state(target):
                        return
                await self._evaluate_locked()
        except asyncio.CancelledError:
            return

    async def _try_apply_state(self, active: bool) -> bool:
        try:
            await self._apply_state(active)
        except RuleSuspended:
            self._show_suspended()
            return False
        except Exception as err:
            self.last_error = str(err)
            self.status = "error"
            _LOGGER.exception("EntityCraft rule %s failed during %s", self.entry.entry_id,
                              "activation" if active else "restoration")
            action = self.config[CONF_TRIGGER_ACTION if active else CONF_RESET_ACTION]
            if self._toggle_pending:
                self._blocked_error = "Toggle outcome is uncertain; manual recovery required"
            elif action != ACTION_TOGGLE:
                self._schedule_retry()
            self._notify()
            return False
        self.last_error = None
        self._cancel_retry()
        return True

    def _schedule_retry(self) -> None:
        if self._stopped or not self.enabled or self._retry_task:
            return
        self._retry_task = self.hass.async_create_task(self._retry())

    async def _retry(self) -> None:
        try:
            await asyncio.sleep(RETRY_DELAY)
            self._retry_task = None
            await self.async_evaluate()
        except asyncio.CancelledError:
            return

    def _cancel_retry(self) -> None:
        if self._retry_task and not self._retry_task.done():
            self._retry_task.cancel()
        self._retry_task = None

    @staticmethod
    def _target_entity_ids(target: dict) -> list[str]:
        value = target.get("entity_id", [])
        if isinstance(value, str):
            return [value]
        return list(value)

    def _snapshot_entity_ids(self) -> list[str]:
        config = self.config
        explicit = config.get(CONF_SNAPSHOT_ENTITIES, [])
        if isinstance(explicit, str):
            explicit = [explicit]
        if explicit:
            return list(explicit)

        return [
            entity_id
            for entity_id in self._target_entity_ids(config[CONF_TRIGGER_TARGET])
            if not entity_id.startswith("scene.")
        ]

    async def _save(
        self, active: bool, snapshot: dict | None, *, toggle_pending: bool | None = None
    ) -> None:
        data = json.loads(json.dumps({
            "enabled": self.enabled, "active": active, "snapshot": snapshot,
            "binding": self._binding(),
            "toggle_pending": self._toggle_pending if toggle_pending is None else toggle_pending,
        }))
        await self._store.async_save(data)
        # Store logs some disk/serialization errors without raising. Read with
        # a fresh instance so a pending in-memory write cannot masquerade as a
        # durable original state (notably during HA shutdown).
        persisted = await Store(
            self.hass, 1, f"{DOMAIN}.{self.entry.entry_id}", atomic_writes=True
        ).async_load()
        if persisted != data:
            raise OSError("Recovery state could not be verified on disk")

    async def _create_snapshot_scene(self) -> None:
        await self.hass.services.async_call(
            "scene", "create",
            {"scene_id": self._snapshot_scene, "entities": self._saved_states},
            blocking=True,
        )
        if self.hass.states.get(f"scene.{self._snapshot_scene}") is None:
            raise ValueError("Snapshot scene was not created")

    def _snapshot_is_restored(self) -> bool:
        """Check reported states; for lights also check their active color mode."""
        for entity_id, saved in (self._saved_states or {}).items():
            current = self.hass.states.get(entity_id)
            if current is None or current.state != saved["state"]:
                return False
            if not entity_id.startswith("light.") or saved["state"] != "on":
                continue
            checks = {"brightness": 2, "effect": 0, "color_mode": 0}
            mode = saved.get("color_mode")
            color_attribute = {
                "hs": ("hs_color", 2), "xy": ("xy_color", 0.01),
                "rgb": ("rgb_color", 3), "rgbw": ("rgbw_color", 3),
                "rgbww": ("rgbww_color", 3), "color_temp": ("color_temp_kelvin", 50),
            }.get(mode)
            if color_attribute:
                checks[color_attribute[0]] = color_attribute[1]
            for key, tolerance in checks.items():
                expected = saved.get(key)
                if expected is None:
                    continue
                actual = current.attributes.get(key)
                if isinstance(expected, (list, tuple)):
                    if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
                        return False
                    if any(abs(a - b) > tolerance for a, b in zip(actual, expected)):
                        return False
                elif isinstance(expected, (int, float)):
                    if not isinstance(actual, (int, float)) or abs(actual - expected) > tolerance:
                        return False
                elif actual != expected:
                    return False
        return True

    async def _wait_for_restore(self) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + RESTORE_TIMEOUT
        matched_since: float | None = None
        while True:
            if self._stopped or not self.enabled:
                raise InterruptedError("Restoration interrupted; original state remains saved")
            # Even on reopening, wait for the restoration already sent to be
            # reported before sending red again. Otherwise its late report can
            # overwrite the new warning. _apply_state retains the original.
            now = loop.time()
            if self._snapshot_is_restored():
                if matched_since is None:
                    matched_since = now
                if now - matched_since >= RESTORE_STABLE_TIME:
                    return
            else:
                matched_since = None
            if now >= deadline:
                raise TimeoutError("Restored state has not been confirmed by the device")
            await asyncio.sleep(RESTORE_POLL_INTERVAL)

    async def _apply_state(self, active: bool) -> None:
        config = self.config
        if self._is_suspended():
            raise RuleSuspended

        if active:
            self.is_active = True
            self.status = "triggering"
            needs_snapshot = config[CONF_RESET_ACTION] == ACTION_RESTORE_PREVIOUS
            entity_ids = self._snapshot_entity_ids() if needs_snapshot else []
            if config[CONF_RESET_ACTION] == ACTION_RESTORE_PREVIOUS and not entity_ids:
                raise ValueError("No snapshot entities configured for restore_previous")
            if entity_ids and not self._snapshot_taken:
                snapshot = {}
                for entity_id in entity_ids:
                    if entity_id.startswith("scene."):
                        raise ValueError("Snapshot the affected entities, not scene entities")
                    state = self.hass.states.get(entity_id)
                    if state is None or state.state in ("unknown", "unavailable"):
                        raise ValueError(f"Cannot snapshot unavailable entity: {entity_id}")
                    snapshot[entity_id] = {**deepcopy(dict(state.attributes)), "state": state.state}
                self._saved_states = snapshot
                self._snapshot_taken = True
            # Persist BEFORE any alarm command. Repeated failures and restarts
            # retain this snapshot rather than capturing the alarm color.
            await self._save(True, self._saved_states)
            if self._saved_states:
                await self._create_snapshot_scene()
            if self._stopped or not self.enabled:
                raise InterruptedError("Activation interrupted before sending command")
            if self._is_suspended():
                raise RuleSuspended
            if config[CONF_TRIGGER_ACTION] == ACTION_TOGGLE:
                self._toggle_pending = True
                await self._save(True, self._saved_states)
            await self.hass.services.async_call(
                "homeassistant",
                config[CONF_TRIGGER_ACTION],
                {},
                target=config[CONF_TRIGGER_TARGET],
                blocking=True,
            )
            self._activation_complete = True
            self._restoring = False
            if self._toggle_pending:
                # Keep the uncertainty flag if saving completion fails.
                await self._save(True, self._saved_states, toggle_pending=False)
                self._toggle_pending = False
        elif config[CONF_RESET_ACTION] == ACTION_RESTORE_PREVIOUS:
            self.status = "restoring"
            self._restoring = True
            if not self._snapshot_taken or not self._saved_states:
                raise ValueError("Previous state is missing; alarm has not been cleared")
            # Dynamic HA scenes disappear on restart or scene.reload. Rebuild
            # from the saved original, never from the current alarm state.
            await self._create_snapshot_scene()
            await self.hass.services.async_call(
                "scene",
                "turn_on",
                {},
                target={"entity_id": f"scene.{self._snapshot_scene}"},
                blocking=True,
            )
            await self._wait_for_restore()
        else:
            self._restoring = True
            if config[CONF_RESET_ACTION] == ACTION_TOGGLE:
                self._toggle_pending = True
                await self._save(True, self._saved_states)
            await self.hass.services.async_call(
                "homeassistant",
                config[CONF_RESET_ACTION],
                {},
                target=config[CONF_RESET_TARGET],
                blocking=True,
            )

        if not active:
            self._activation_complete = False
            if self._condition_matches():
                # A door reopened during restoration. Retain the original
                # snapshot for this alarm episode and re-apply the alarm next.
                self.is_active = True
                if self._toggle_pending:
                    await self._save(True, self._saved_states, toggle_pending=False)
                    self._toggle_pending = False
            else:
                await self._save(False, None, toggle_pending=False)
                self._toggle_pending = False
                self.is_active = False
                self._snapshot_taken = False
                self._saved_states = None
                self._restoring = False
        self.status = "active" if self.is_active else "ready"
        self._notify()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        async with self._transition_lock:
            if not self._blocked_error:
                await self._save(self.is_active, self._saved_states)
        await self.async_evaluate()

    def _cancel_delay(self) -> None:
        if self._delay_task and not self._delay_task.done():
            self._delay_task.cancel()
        self._delay_task = None
        self._delay_target = None
