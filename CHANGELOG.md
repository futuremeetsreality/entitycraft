# Changelog

## 0.1.4

- Serialize alarm and restore actions so rapid sensor changes cannot overwrite the original state with the alarm state.
- Persist recovery snapshots before activation; restore them after restart or scene reload.
- Confirm reported light state, brightness and color before clearing the alarm; keep the original and retry on failure.
- Preserve running delays when the aggregate condition stays unchanged; never cancel an in-flight action when a timer is canceled.
- Add an unavailable-input policy: hold by default, or explicitly activate a warning alarm.
- Expose errors and unavailable inputs; stop ambiguous failed toggles instead of repeating them.
- Repair the Configure dialog for current Home Assistant and prevent duplicate reloads and stale option overrides.
- Add deterministic runtime and configuration regression tests and CI.

## 0.1.2

- restore the target entity's previous state after a rule resets
- add a visible Configure options flow for editing existing rules
- reload rules automatically after UI changes

