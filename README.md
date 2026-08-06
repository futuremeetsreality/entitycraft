# EntityCraft

**Complex automations. Simple control.**

EntityCraft is a UI-first, explainable and portable rule engine for Home Assistant.

## Alpha 0.1

The first alpha targets one real workflow: monitor multiple binary sensors and activate a Home Assistant scene when the rule becomes true, then activate a reset scene when it becomes false again.

Current branch capabilities:

- UI-only rule creation
- multiple binary sensors
- ANY / ALL logic
- active or inactive trigger state
- trigger and reset delays
- trigger and reset scenes
- enable switch
- live alarm and status entities

> Project status: early alpha. Not yet validated on a real Home Assistant installation.
