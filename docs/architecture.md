# Architecture

EntityCraft separates portable rule definitions from local Home Assistant bindings.

## Layers

1. **Rule Package** — metadata, declared inputs, conditions and action definitions.
2. **Bindings** — maps abstract input keys to local Home Assistant entities.
3. **Evaluation Engine** — evaluates conditions without side effects.
4. **Explain Engine** — produces human-readable reasons for every result.
5. **Runtime** — handles delays, cancellation, activation and action execution.
6. **UI** — editor, live evaluation, history and rule management.

## Core rule

Concrete entity IDs must never be stored inside portable rule definitions. They belong only to local bindings.

## Preview safety

Live evaluation is read-only. It may calculate what would happen, but must never call a Home Assistant action.
