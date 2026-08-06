# Roadmap

## 0.1 Foundation

- Home Assistant integration skeleton
- UI config flow
- German and English localization
- architecture and portable rule package
- HACS metadata

## 0.2 Rule model

- create, edit, enable and disable rules through UI
- abstract inputs and local bindings
- binary sensor conditions
- AND / OR evaluation

## 0.3 Runtime

- trigger and reset delays
- light, switch, scene and script actions
- cancellation-safe state machine
- per-rule status entities

## 0.4 Explainable UI

- live read-only evaluation
- clear reason for every condition result
- pending-delay countdown
- rule-specific history

## 1.0

- complete UI-only door and sensor monitoring workflow
- portable import/export format
- stable migrations and tests
- initial documentation and HACS release

The marketplace service is planned after 1.0, but the 1.0 rule format is designed for it from the beginning.
