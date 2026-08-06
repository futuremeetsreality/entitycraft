"""Constants for EntityCraft."""

DOMAIN = "entitycraft"
PLATFORMS = ["binary_sensor", "switch", "sensor"]

CONF_ENTITIES = "entities"
CONF_LOGIC = "logic"
CONF_ACTIVE_STATE = "active_state"
CONF_DELAY = "delay"
CONF_TRIGGER_TARGET = "trigger_target"
CONF_TRIGGER_ACTION = "trigger_action"
CONF_SNAPSHOT_ENTITIES = "snapshot_entities"
CONF_RESET_DELAY = "reset_delay"
CONF_RESET_TARGET = "reset_target"
CONF_RESET_ACTION = "reset_action"

ACTION_TURN_ON = "turn_on"
ACTION_TURN_OFF = "turn_off"
ACTION_TOGGLE = "toggle"
ACTION_RESTORE_PREVIOUS = "restore_previous"

LOGIC_ANY = "any"
LOGIC_ALL = "all"
