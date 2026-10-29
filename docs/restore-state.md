# Restore state

When a rule triggers with `restore_previous`, EntityCraft captures the selected snapshot entities **once per alarm episode**, before sending the trigger action. The original is saved in Home Assistant's local storage and read back before sending the alarm command. A second opening, a retry, or a reopening during restoration keeps that original.

Only one transition per rule runs at a time. Sensor changes received while a command runs are evaluated again afterward. Waiting trigger/reset timers can be canceled; an action already sent to a device is allowed to finish. Additional events for the same aggregate condition do not restart a timer.

On reset, EntityCraft creates a temporary scene from the saved original and activates it. It then waits up to 10 seconds for reported entity states to match. For an on-state light, this also checks brightness, effect, active color mode and its color attribute, with small tolerances for device rounding. A matching state must remain reported for 0.3 seconds. Other domains are checked by state only. This confirms Home Assistant's reported state, not independent physical feedback from the bulb.

If restoration fails or is not confirmed, the alarm remains active, the original remains saved, and the status becomes `error` with a `last_error` attribute. Idempotent `turn_on`, `turn_off`, and restore actions are retried after five seconds. Do not use a script or scene with non-idempotent side effects as a retryable action. An uncertain `toggle` is never automatically repeated, including after restart; it requires manual recovery.

## Unknown inputs

Unknown, missing and unavailable sensors never clear an existing alarm. The default **Hold last alarm state** policy avoids starting new actions for unrelated rules when a sensor is offline; an inactive alarm sensor becomes unavailable instead of reporting an all-clear. **Activate alarm (fail-safe)** also activates the configured action when any input is unknown. Use this policy for a door-warning light that should indicate a problem whenever closure cannot be confirmed.

For door monitoring, use ANY + `on`, immediate activation, explicit snapshot light entities, and `restore_previous`. A reset delay of 2–3 seconds is useful to require a short continuously closed period. If a trigger scene changes additional entities, include every restorable entity you need in the snapshot, or simplify the scene to change only the warning light.

## Restart, editing and recovery

Recovery data is local to this Home Assistant instance under `.storage/entitycraft.<entry_id>` and survives restart and temporary-scene reload. The enable switch also survives a restart. Do not edit or delete storage files manually. Deleting the rule removes its recovery data.

Sensor/action bindings cannot be changed through the editor while an alarm is active. The runtime also rejects an active saved snapshot whose bindings have changed externally. Missing, invalid or incomplete recovery data produces an error; it must not be replaced with a snapshot of an already-red lamp.

For an uncertain toggle or damaged recovery data: disable the rule, verify the physical sensors and controlled devices, establish the intended normal state manually, and recreate the rule when safe. Changing configuration back to the stored bindings can recover a configuration-mismatch error. Do not suppress a warning while any monitored door is open or unknown.

**Upgrading from 0.1.3:** the earlier version did not save durable recovery data. Before the first restart into 0.1.4, finish any active alarm and establish a known normal lamp state with all sensors confirmed closed. An original already overwritten with red cannot be reconstructed by this update. Keep a backup of the previous integration and rule settings.

This is a convenience indicator, not a certified alarm system. Device/network outages, optimistic device reporting, another automation changing the same light, and power loss can still prevent the physical light from matching the requested state. Avoid having multiple EntityCraft rules or other automations control the same warning light during an alarm.

## Validation

Run `python -B -m unittest discover -s tests -v`. The suite uses asynchronous HA service/storage test doubles and no real devices. It covers overlapping commands, reopening during restoration, delayed and missing device reports, error retries, unavailable inputs, persistence, scene reloads, interrupted actions, toggles, and configuration flows. It does not replace a smoke test on the installed Home Assistant version and physical lamp.
