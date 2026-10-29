# Restore state

When a rule triggers with `restore_previous`, EntityCraft captures the selected snapshot entities **once per alarm episode**, before sending the trigger action. The original is saved in Home Assistant's local storage and read back before sending the alarm command. A second opening, a retry, or a reopening during restoration keeps that original.

Only one transition per rule runs at a time. Sensor changes received while a command runs are evaluated again afterward. Waiting trigger/reset timers can be canceled; an action already sent to a device is allowed to finish. Additional events for the same aggregate condition do not restart a timer.

Rules with overlapping explicit snapshot/target entities also serialize their commands. On reopening during restoration, an already-sent restoration must finish reporting before the warning is reapplied, so a late restore cannot immediately overwrite the renewed warning. The same bounded timeout and error handling still apply.

On reset, EntityCraft creates a temporary scene from the saved original and activates it. It then waits up to 10 seconds for reported entity states to match. For an on-state light, this also checks brightness, effect, active color mode and its color attribute, with small tolerances for device rounding. A matching state must remain reported for 0.3 seconds. Other domains are checked by state only. This confirms Home Assistant's reported state, not independent physical feedback from the bulb.

If restoration fails or is not confirmed, the alarm remains active, the original remains saved, and the status becomes `error` with a `last_error` attribute. Idempotent `turn_on`, `turn_off`, and restore actions are retried after five seconds. Do not use a script or scene with non-idempotent side effects as a retryable action. An uncertain `toggle` is never automatically repeated, including after restart; it requires manual recovery.

## Unknown inputs

Unknown, missing and unavailable sensors never clear an existing alarm. The default **Hold last alarm state** policy avoids starting new actions for unrelated rules when a sensor is offline; an inactive alarm sensor becomes unavailable instead of reporting an all-clear. **Activate alarm (fail-safe)** also activates the configured action when any input is unknown. Use this policy for a door-warning light that should indicate a problem whenever closure cannot be confirmed.

For door monitoring, use ANY + `on`, immediate activation, explicit snapshot light entities, and `restore_previous`. A reset delay of 2–3 seconds is useful to require a short continuously closed period. If a trigger scene changes additional entities, include every restorable entity you need in the snapshot, or simplify the scene to change only the warning light.

## Sharing a light with a lower-priority indicator

Use **Suspend while these sensors are on or unavailable** on the lower-priority rule, for example a green activity indicator sharing a red door-warning bulb. Select **both all raw door sensors and the door rule's Alarm entity**. The raw sensors prevent a competing action before the alarm entity has updated; the Alarm entity keeps the secondary rule suspended throughout the door rule's reset delay and restoration. Leave this field empty on the door-warning rule. Do not create mutual dependencies or select a rule's own Alarm entity.

While suspended, a rule takes no new snapshot and sends no trigger or reset action. It keeps any original already saved. Missing or unavailable guard sensors also suspend it. The status is `suspended`, with a `suspended_by` attribute listing the guards. Once every guard reports off, the rule evaluates its current input again. For example, if the secondary activity ended during a door warning, its previously deferred restoration runs after the door warning finishes. This prevents red from becoming the secondary rule's normal state.

Configure this explicitly; installing the update does not infer priorities or alter existing rule bindings. For indirect scenes, include the actual shared light in each rule's snapshot entities so output serialization can identify the overlap. Area/device targets and arbitrary script side effects are not expanded into locks. External automations do not participate in these locks or guards and must not write to the warning light during an alarm. An already-sent command is allowed to finish before the next rule acts, which can delay the warning while its reported completion is awaited.

## Restart, editing and recovery

Recovery data is local to this Home Assistant instance under `.storage/entitycraft.<entry_id>` and survives restart and temporary-scene reload. The enable switch also survives a restart. Do not edit or delete storage files manually. Deleting the rule removes its recovery data.

Sensor/action bindings cannot be changed through the editor while an alarm is active. The runtime also rejects an active saved snapshot whose bindings have changed externally. Missing, invalid or incomplete recovery data produces an error; it must not be replaced with a snapshot of an already-red lamp.

For an uncertain toggle or damaged recovery data: disable the rule, verify the physical sensors and controlled devices, establish the intended normal state manually, and recreate the rule when safe. Changing configuration back to the stored bindings can recover a configuration-mismatch error. Do not suppress a warning while any monitored door is open or unknown.

**Upgrading from 0.1.3:** the earlier version did not save durable recovery data. Before the first restart into 0.1.4, finish any active alarm and establish a known normal lamp state with all sensors confirmed closed. An original already overwritten with red cannot be reconstructed by this update. Keep a backup of the previous integration and rule settings.

This is a convenience indicator, not a certified alarm system. Device/network outages, optimistic or out-of-order device reporting, another automation changing the same light, and power loss can still prevent the physical light from matching the requested state. Configure the guards above for shared EntityCraft indicators and prevent other automations from overriding an active warning.

## Validation

Run `python -B -m unittest discover -s tests -v`. The suite uses asynchronous HA service/storage test doubles and no real devices. It covers overlapping commands, reopening during restoration, delayed and missing device reports, error retries, unavailable inputs, persistence, scene reloads, interrupted actions, toggles, and configuration flows. It does not replace a smoke test on the installed Home Assistant version and physical lamp.
