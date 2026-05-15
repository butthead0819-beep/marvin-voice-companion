"""Lane G 新增事件常數測試：temperature_update、topic_generated。"""

from companion.event_protocol import (
    validate_event,
    TEMPERATURE_UPDATE,
    TOPIC_GENERATED,
    BRIDGE_TO_BROWSER_EVENTS,
)


def test_temperature_update_is_valid():
    event = {"type": "temperature_update", "payload": {"level": "cold", "value": 0.2}, "ts": 1.0}
    assert validate_event(event) is True


def test_topic_generated_is_valid():
    event = {"type": "topic_generated", "payload": {"topics": ["話題一"], "trigger": "auto"}, "ts": 1.0}
    assert validate_event(event) is True


def test_temperature_update_in_bridge_to_browser():
    assert TEMPERATURE_UPDATE in BRIDGE_TO_BROWSER_EVENTS


def test_topic_generated_in_bridge_to_browser():
    assert TOPIC_GENERATED in BRIDGE_TO_BROWSER_EVENTS
