"""Flow regression tests using HA's public flow interfaces as test doubles."""

import importlib
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock

from test_runtime import runtime  # Installs the isolated HA module doubles.


class BaseFlow:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}

    def _get_reconfigure_entry(self):
        return self._entry


class OptionsFlow(BaseFlow):
    @property
    def config_entry(self):
        # Current HA exposes this as read-only; assigning it in __init__ breaks.
        return self._entry


entries = sys.modules["homeassistant.config_entries"]
entries.ConfigFlow = BaseFlow
entries.OptionsFlow = OptionsFlow
vol = ModuleType("voluptuous")
vol.Schema = lambda schema: schema
vol.Required = lambda key, **kwargs: key
vol.Optional = lambda key, **kwargs: key
sys.modules["voluptuous"] = vol
const = ModuleType("homeassistant.const")
const.CONF_NAME = "name"
sys.modules[const.__name__] = const
data_entry_flow = ModuleType("homeassistant.data_entry_flow")
data_entry_flow.FlowResult = dict
sys.modules[data_entry_flow.__name__] = data_entry_flow
selector = MagicMock()
sys.modules["homeassistant.helpers"].selector = selector
flow_module = importlib.import_module("entitycraft_runtime_test.config_flow")


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {
            "name": "Door", "entities": ["binary_sensor.test"], "logic": "any",
            "active_state": "on", "delay": 0, "reset_delay": 2,
            "trigger_target": {"entity_id": "scene.red"}, "trigger_action": "turn_on",
            "snapshot_entities": ["light.test"],
            "reset_target": {"entity_id": "light.test"}, "reset_action": "restore_previous",
        }
        self.entry = SimpleNamespace(entry_id="test", title="Door", data=self.config,
                                     options={"reset_delay": 5})
        self.hass = SimpleNamespace(data={}, config_entries=SimpleNamespace(
            async_update_entry=MagicMock(), async_reload=AsyncMock(),
        ))

    def prepare(self, flow):
        flow.hass = self.hass
        flow._entry = self.entry
        return flow

    async def test_options_construct_without_assigning_readonly_config_entry(self):
        flow = self.prepare(flow_module.EntityCraftConfigFlow.async_get_options_flow(self.entry))
        result = await flow.async_step_init()
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {})

    async def test_reconfigure_clears_stale_options_and_does_not_double_reload(self):
        flow = self.prepare(flow_module.EntityCraftConfigFlow())
        result = await flow.async_step_reconfigure(self.config)
        self.assertEqual(result["reason"], "reconfigure_successful")
        self.hass.config_entries.async_update_entry.assert_called_once_with(
            self.entry, title="Door", data=self.config, options={},
        )
        self.hass.config_entries.async_reload.assert_not_awaited()

    async def test_new_rule_rejects_empty_inputs(self):
        flow = self.prepare(flow_module.EntityCraftConfigFlow())
        result = await flow.async_step_user({**self.config, "entities": []})
        self.assertEqual(result["errors"], {"entities": "no_sensors"})

    async def test_scene_restore_requires_explicit_snapshot_entities(self):
        result = flow_module._validate({**self.config, "snapshot_entities": []})
        self.assertEqual(result, {"snapshot_entities": "no_snapshot_entities"})

    async def test_direct_light_restore_accepts_implicit_snapshot(self):
        result = flow_module._validate({**self.config, "snapshot_entities": [],
                                       "trigger_target": {"entity_id": "light.test"}})
        self.assertEqual(result, {})

    async def test_active_rule_cannot_rebind_inputs_or_targets(self):
        self.hass.data = {"entitycraft": {"test": SimpleNamespace(is_active=True, config=self.config)}}
        changed = {**self.config, "snapshot_entities": ["light.different"]}
        for flow, step in ((flow_module.EntityCraftConfigFlow(), "async_step_reconfigure"),
                           (flow_module.EntityCraftOptionsFlow(), "async_step_init")):
            result = await getattr(self.prepare(flow), step)(changed)
            self.assertEqual(result["errors"], {"base": "alarm_active"})
        self.hass.config_entries.async_update_entry.assert_not_called()

    async def test_active_rule_can_change_delay_without_rebinding(self):
        self.hass.data = {"entitycraft": {"test": SimpleNamespace(is_active=True, config=self.config)}}
        flow = self.prepare(flow_module.EntityCraftOptionsFlow())
        result = await flow.async_step_init({**self.config, "reset_delay": 3})
        self.assertEqual(result["type"], "create_entry")
