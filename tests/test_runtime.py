"""Deterministic runtime tests with a small, asynchronous HA service double.

No real devices or Home Assistant installation are used. The double deliberately
lets commands remain in flight while sensor events arrive.
"""

import asyncio
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class FakeState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class FakeStore:
    def __init__(self, hass, version, key, **kwargs):
        self.hass, self.key = hass, key

    async def async_load(self):
        return deepcopy(self.hass.storage.get(self.key))

    async def async_save(self, data):
        if self.hass.storage_fails:
            raise OSError("simulated disk failure")
        if self.hass.storage_silent_failure:
            return
        self.hass.storage[self.key] = deepcopy(data)

    async def async_remove(self):
        self.hass.storage.pop(self.key, None)


def load_runtime():
    modules = {}
    for name in ("homeassistant", "homeassistant.core", "homeassistant.config_entries",
                 "homeassistant.helpers", "homeassistant.helpers.event",
                 "homeassistant.helpers.storage", "homeassistant.exceptions"):
        modules[name] = ModuleType(name)
    modules["homeassistant.core"].callback = lambda func: func
    modules["homeassistant.core"].Event = object
    modules["homeassistant.core"].HomeAssistant = object
    modules["homeassistant.config_entries"].ConfigEntry = object
    modules["homeassistant.helpers.storage"].Store = FakeStore
    modules["homeassistant.exceptions"].HomeAssistantError = RuntimeError
    modules["homeassistant.helpers.event"].async_track_state_change_event = (
        lambda hass, ids, callback: hass.listen(ids, callback)
    )
    sys.modules.update(modules)
    package = ModuleType("entitycraft_runtime_test")
    package.__path__ = [str(ROOT / "custom_components" / "entitycraft")]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location(
        package.__name__ + ".runtime", Path(package.__path__[0]) / "runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runtime = load_runtime()


class FakeHass:
    def __init__(self):
        self.states = {
            "binary_sensor.a": FakeState("off"),
            "binary_sensor.b": FakeState("off"),
            "light.test": FakeState("on", {"color_mode": "hs", "hs_color": [240, 100], "brightness": 120}),
        }
        self.storage = {}
        self.storage_fails = False
        self.storage_silent_failure = False
        self.calls = []
        self.snapshots = {}
        self.tasks = []
        self.listeners = []
        self.services = SimpleNamespace(async_call=self.call)
        self.block_action = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.fail_action = None
        self.silent_restore = False
        self.report_delay = 0
        self.report_gate = None
        self.report_entered = asyncio.Event()

    def listen(self, ids, callback):
        item = (ids, callback)
        self.listeners.append(item)
        return lambda: self.listeners.remove(item)

    def async_create_task(self, coro, *args, **kwargs):
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task

    async def call(self, domain, service, data, *, target=None, blocking=False):
        action = (domain, service)
        self.calls.append((action, deepcopy(data), deepcopy(target)))
        if action == self.block_action:
            self.entered.set()
            await self.release.wait()
        if action == self.fail_action:
            raise RuntimeError("simulated device failure")
        if action == ("scene", "create"):
            snapshot = deepcopy(data.get("entities", {}))
            for entity_id in data.get("snapshot_entities", []):
                state = self.states[entity_id]
                snapshot[entity_id] = {**deepcopy(state.attributes), "state": state.state}
            scene = "scene." + data["scene_id"]
            self.snapshots[scene] = snapshot
            self.states[scene] = FakeState("unknown")
        elif domain == "homeassistant":
            self.states["light.test"] = FakeState("on", {"color_mode": "hs", "hs_color": [0, 100], "brightness": 255})
        elif action in (("scene", "turn_on"), ("scene", "apply")):
            snapshot = data["entities"] if service == "apply" else self.snapshots[target["entity_id"]]
            self.report_entered.set()
            if self.silent_restore:
                return
            if self.report_delay:
                self.async_create_task(self.report_later(deepcopy(snapshot)))
            else:
                self.report(snapshot)

    def report(self, snapshot):
        for entity_id, saved in snapshot.items():
            attrs = deepcopy(saved)
            state = attrs.pop("state")
            self.states[entity_id] = FakeState(state, attrs)

    async def report_later(self, snapshot):
        if self.report_gate is not None:
            await self.report_gate.wait()
        await asyncio.sleep(self.report_delay)
        self.report(snapshot)

    def set_sensor(self, entity_id, state):
        self.states[entity_id] = FakeState(state)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.constants = patch.multiple(runtime, RESTORE_STABLE_TIME=0.005,
                                        RESTORE_POLL_INTERVAL=0.002, RESTORE_TIMEOUT=0.1,
                                        RETRY_DELAY=0.02)
        self.constants.start()
        self.addCleanup(self.constants.stop)
        self.logs = patch.object(runtime._LOGGER, "exception")
        self.logs.start()
        self.addCleanup(self.logs.stop)
        self.hass = FakeHass()
        self.entry = SimpleNamespace(entry_id="test123", title="Door monitor", options={}, data={
            "entities": ["binary_sensor.a", "binary_sensor.b"], "logic": "any",
            "active_state": "on", "delay": 0, "reset_delay": 0,
            "unavailable_policy": "activate",
            "trigger_target": {"entity_id": "scene.alarm"}, "trigger_action": "turn_on",
            "snapshot_entities": ["light.test"],
            "reset_target": {"entity_id": "light.test"}, "reset_action": "restore_previous",
        })
        self.rule = runtime.EntityCraftRule(self.hass, self.entry)
        # Tests adjust configuration before driving a transition. Production
        # runtime configuration is frozen until its config entry is reloaded.
        self.entry.options = self.rule._config
        await self.rule.async_start()

    async def asyncTearDown(self):
        self.hass.release.set()
        await self.rule.async_stop()
        for task in self.hass.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.hass.tasks, return_exceptions=True)

    async def change(self, state, entity="binary_sensor.a"):
        self.hass.set_sensor(entity, state)
        await self.rule.async_evaluate()

    async def yield_tasks(self):
        for _ in range(10):
            await asyncio.sleep(0)

    def assert_original(self):
        lamp = self.hass.states["light.test"]
        self.assertEqual(lamp.state, "on")
        self.assertEqual(lamp.attributes["hs_color"], [240, 100])
        self.assertEqual(lamp.attributes["brightness"], 120)

    async def test_close_while_alarm_command_is_in_flight(self):
        self.hass.block_action = ("homeassistant", "turn_on")
        opening = asyncio.create_task(self.change("on"))
        await asyncio.wait_for(self.hass.entered.wait(), 1)
        closing = asyncio.create_task(self.change("off"))
        await self.yield_tasks()
        self.hass.release.set()
        await asyncio.gather(opening, closing)
        self.assert_original()
        self.assertFalse(self.rule.is_active)

    async def test_reopen_during_restore_preserves_original(self):
        await self.change("on")
        self.hass.block_action = ("scene", "turn_on")
        closing = asyncio.create_task(self.change("off"))
        await asyncio.wait_for(self.hass.entered.wait(), 1)
        opening = asyncio.create_task(self.change("on", "binary_sensor.b"))
        await self.yield_tasks()
        self.hass.release.set()
        await asyncio.gather(closing, opening)
        await self.change("off", "binary_sensor.b")
        self.assert_original()

    async def test_another_open_sensor_does_not_replace_snapshot(self):
        await self.change("on")
        await self.change("on", "binary_sensor.b")
        await self.change("off")
        self.assertTrue(self.rule.is_active)
        await self.change("off", "binary_sensor.b")
        self.assert_original()

    async def test_unavailable_sensor_must_not_clear_alarm(self):
        await self.change("on")
        await self.change("unavailable")
        self.assertTrue(self.rule.is_active)
        self.assertNotEqual(self.rule.status, "ready")
        await self.change("off")
        self.assert_original()

    async def test_restore_failure_keeps_alarm_and_original(self):
        await self.change("on")
        self.hass.fail_action = ("scene", "turn_on")
        try:
            await self.change("off")
        except RuntimeError:
            pass
        self.assertTrue(self.rule.is_active)
        self.assertNotEqual(self.rule.status, "ready")
        self.hass.fail_action = None
        await self.rule.async_evaluate()
        self.assert_original()
        self.assertFalse(self.rule.is_active)

    async def test_restart_while_open_preserves_original(self):
        await self.change("on")
        await self.rule.async_stop()
        self.hass.snapshots.clear()
        self.hass.states.pop("scene.test123", None)
        self.rule = runtime.EntityCraftRule(self.hass, self.entry)
        await self.rule.async_start()
        await self.change("off")
        self.assert_original()

    async def test_restart_after_doors_close_restores_pending_snapshot(self):
        await self.change("on")
        await self.rule.async_stop()
        self.hass.set_sensor("binary_sensor.a", "off")
        self.hass.snapshots.clear()
        self.rule = runtime.EntityCraftRule(self.hass, self.entry)
        await self.rule.async_start()
        self.assert_original()
        self.assertFalse(self.rule.is_active)

    async def test_scene_reload_does_not_lose_original(self):
        await self.change("on")
        self.hass.states.pop("scene.entitycraft_test123")
        self.hass.snapshots.clear()
        await self.change("off")
        self.assert_original()

    async def test_originally_off_light_stays_off(self):
        self.hass.states["light.test"] = FakeState("off", {"brightness": 42})
        await self.change("on")
        await self.change("off")
        self.assertEqual(self.hass.states["light.test"].state, "off")

    async def test_same_condition_does_not_restart_delay(self):
        self.entry.options["delay"] = 0.03
        await self.change("on")
        timer = self.rule._delay_task
        await self.change("on", "binary_sensor.b")
        self.assertIs(self.rule._delay_task, timer)
        await asyncio.wait_for(timer, 1)
        self.assertTrue(self.rule.is_active)

    async def test_close_during_delay_does_not_trigger(self):
        self.entry.options["delay"] = 0.03
        await self.change("on")
        await self.change("off")
        await asyncio.sleep(0.05)
        self.assertFalse(self.rule.is_active)
        self.assertEqual(self.hass.calls, [])

    async def test_missing_input_at_start_is_not_all_clear(self):
        self.hass.states.pop("binary_sensor.a")
        await self.rule.async_evaluate()
        self.assertTrue(self.rule.is_active)
        self.assertEqual(self.rule.status, "input_unavailable")

    async def test_error_retry_keeps_the_original_snapshot(self):
        self.hass.fail_action = ("homeassistant", "turn_on")
        await self.change("on")
        # Model a command that took effect before the integration reported error.
        self.hass.states["light.test"] = FakeState("on", {"hs_color": [0, 100]})
        self.hass.fail_action = None
        await self.rule.async_evaluate()
        await self.change("off")
        self.assert_original()

    async def test_delayed_device_report_must_finish_before_all_clear(self):
        await self.change("on")
        self.hass.report_delay = 0.001
        self.hass.report_gate = asyncio.Event()
        closing = asyncio.create_task(self.change("off"))
        await asyncio.wait_for(self.hass.report_entered.wait(), 1)
        self.assertTrue(self.rule.is_active)
        self.assertEqual(self.rule.status, "restoring")
        self.hass.report_gate.set()
        await closing
        self.assert_original()
        self.assertFalse(self.rule.is_active)

    async def test_restore_without_device_confirmation_stays_active_and_retries(self):
        await self.change("on")
        self.hass.silent_restore = True
        await self.change("off")
        self.assertTrue(self.rule.is_active)
        self.assertEqual(self.rule.status, "error")
        self.assertIsNotNone(self.rule.last_error)
        self.hass.silent_restore = False
        retry = self.rule._retry_task
        await asyncio.wait_for(retry, 1)
        self.assert_original()
        self.assertFalse(self.rule.is_active)

    async def test_reopen_after_partial_failed_restore_reasserts_alarm(self):
        await self.change("on")
        self.hass.silent_restore = True
        await self.change("off")
        self.hass.silent_restore = False
        # The failed restore could have partially reached a multi-entity target.
        self.hass.states["light.test"] = FakeState("off")
        await self.change("on")
        self.assertEqual(self.hass.states["light.test"].attributes["hs_color"], [0, 100])
        await self.change("off")
        self.assert_original()

    async def test_unload_during_unconfirmed_restore_retains_recovery_data(self):
        await self.change("on")
        self.hass.silent_restore = True
        closing = asyncio.create_task(self.change("off"))
        await asyncio.wait_for(self.hass.report_entered.wait(), 1)
        await self.rule.async_stop()
        await closing
        self.assertTrue(self.rule.is_active)
        self.assertTrue(self.hass.storage["entitycraft.test123"]["active"])
        self.hass.silent_restore = False
        self.rule = runtime.EntityCraftRule(self.hass, self.entry)
        await self.rule.async_start()
        self.assert_original()

    async def test_disable_while_restoring_does_not_discard_original(self):
        await self.change("on")
        self.hass.silent_restore = True
        closing = asyncio.create_task(self.change("off"))
        await asyncio.wait_for(self.hass.report_entered.wait(), 1)
        await self.rule.async_set_enabled(False)
        await closing
        self.assertTrue(self.hass.storage["entitycraft.test123"]["active"])
        self.hass.silent_restore = False
        await self.rule.async_set_enabled(True)
        self.assert_original()

    async def test_delayed_activation_is_not_cancelled_mid_command(self):
        self.entry.options["delay"] = 0.005
        self.hass.block_action = ("homeassistant", "turn_on")
        await self.change("on")
        await asyncio.wait_for(self.hass.entered.wait(), 1)
        closing = asyncio.create_task(self.change("off"))
        await self.yield_tasks()
        self.hass.release.set()
        await closing
        self.assert_original()

    async def test_repeated_complete_cycles_capture_new_baseline(self):
        for brightness in (10, 42, 160, 200):
            self.hass.states["light.test"] = FakeState("on", {
                "color_mode": "xy", "xy_color": [0.3, 0.35], "brightness": brightness,
            })
            await self.change("on")
            await self.change("on", "binary_sensor.b")
            await self.change("off")
            await self.change("off", "binary_sensor.b")
            self.assertEqual(self.hass.states["light.test"].attributes["brightness"], brightness)
            self.assertEqual(self.hass.states["light.test"].attributes["xy_color"], [0.3, 0.35])

    async def test_generic_default_holds_on_unknown_without_triggering(self):
        self.entry.options["unavailable_policy"] = "hold"
        await self.change("unavailable")
        self.assertEqual(self.hass.calls, [])
        self.assertEqual(self.rule.status, "input_unavailable")
        await self.change("on")
        await self.change("unknown")
        self.assertTrue(self.rule.is_active)

    async def test_storage_failure_prevents_alarm_command(self):
        self.hass.storage_fails = True
        await self.change("on")
        self.assertEqual(self.hass.calls, [])
        self.assertEqual(self.rule.status, "error")
        self.hass.storage_fails = False
        await self.rule.async_evaluate()
        await self.change("off")
        self.assert_original()

    async def test_logged_but_swallowed_storage_error_is_detected(self):
        self.hass.storage_silent_failure = True
        await self.change("on")
        self.assertEqual(self.hass.calls, [])
        self.assertEqual(self.rule.status, "error")
        self.hass.storage_silent_failure = False
        await self.rule.async_evaluate()
        await self.change("off")
        self.assert_original()

    async def test_input_change_while_waiting_to_restore_cancels_reset(self):
        self.entry.options["reset_delay"] = 0.02
        await self.change("on")
        await self.change("off")
        await self.change("on", "binary_sensor.b")
        await asyncio.sleep(0.03)
        self.assertTrue(self.rule.is_active)
        self.assertEqual(self.hass.states["light.test"].attributes["hs_color"], [0, 100])
        await self.change("off", "binary_sensor.b")
        await asyncio.wait_for(self.rule._delay_task, 1)
        self.assert_original()

    async def test_entry_mutation_does_not_change_inflight_rule_configuration(self):
        self.entry.options = {"trigger_target": {"entity_id": "scene.changed"}}
        await self.change("on")
        trigger = [call for call in self.hass.calls if call[0] == ("homeassistant", "turn_on")]
        self.assertEqual(trigger[0][2], {"entity_id": "scene.alarm"})

    async def test_missing_recovery_snapshot_is_not_replaced_with_red(self):
        await self.change("on")
        await self.rule.async_stop()
        self.hass.storage["entitycraft.test123"]["snapshot"] = None
        self.hass.calls.clear()
        self.rule = runtime.EntityCraftRule(self.hass, self.entry)
        await self.rule.async_start()
        self.assertTrue(self.rule.is_active)
        self.assertEqual(self.rule.status, "error")
        self.assertEqual(self.hass.calls, [])
        self.assertIsNone(self.hass.storage["entitycraft.test123"]["snapshot"])

    async def test_changed_targets_during_alarm_require_recovery(self):
        await self.change("on")
        await self.rule.async_stop()
        self.entry.options["trigger_target"] = {"entity_id": "scene.different"}
        self.hass.calls.clear()
        self.rule = runtime.EntityCraftRule(self.hass, self.entry)
        await self.rule.async_start()
        self.assertEqual(self.rule.status, "error")
        self.assertEqual(self.hass.calls, [])

    async def test_toggle_error_is_not_retried_on_events_or_restart(self):
        self.entry.options["trigger_action"] = "toggle"
        self.hass.fail_action = ("homeassistant", "toggle")
        await self.change("on")
        count = len(self.hass.calls)
        await self.change("on", "binary_sensor.b")
        self.assertEqual(len(self.hass.calls), count)
        await self.rule.async_stop()
        self.rule = runtime.EntityCraftRule(self.hass, self.entry)
        await self.rule.async_start()
        self.assertEqual(len(self.hass.calls), count)
        self.assertEqual(self.rule.status, "error")

    async def test_non_restore_actions_do_not_require_snapshot(self):
        self.entry.options.update(reset_action="turn_off", snapshot_entities=[])
        await self.change("on")
        await self.change("off")
        self.assertFalse(self.rule.is_active)
        self.assertEqual([call[0] for call in self.hass.calls], [
            ("homeassistant", "turn_on"), ("homeassistant", "turn_off"),
        ])

    async def test_disabled_state_survives_restart(self):
        await self.rule.async_set_enabled(False)
        await self.rule.async_stop()
        self.hass.set_sensor("binary_sensor.a", "on")
        self.rule = runtime.EntityCraftRule(self.hass, self.entry)
        await self.rule.async_start()
        self.assertEqual(self.rule.status, "disabled")
        self.assertEqual(self.hass.calls, [])


if __name__ == "__main__":
    unittest.main()
