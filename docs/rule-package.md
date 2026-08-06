# Portable Rule Package

Version 1.0 stores a rule as a portable definition plus installation-specific bindings.

```json
{
  "schema_version": 1,
  "metadata": {
    "name": "Door warning",
    "version": "1.0.0",
    "category": "security"
  },
  "inputs": {
    "doors": {
      "selector": "entity",
      "domain": "binary_sensor",
      "multiple": true,
      "required": true
    },
    "warning_light": {
      "selector": "entity",
      "domain": "light",
      "required": true
    }
  },
  "rule": {
    "logic": "any",
    "conditions": [
      {"input": "doors", "operator": "state", "value": "on"}
    ],
    "actions": [
      {"type": "light", "target": "warning_light", "command": "turn_on"}
    ]
  }
}
```

Local bindings are stored separately:

```json
{
  "doors": ["binary_sensor.front_door", "binary_sensor.patio_door"],
  "warning_light": "light.hall"
}
```

Exports contain the portable package by default and exclude private bindings.
