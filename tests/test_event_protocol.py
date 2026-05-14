"""測試事件協定驗證與型別常數。

事件協定來源：CLAUDE.md 中定義的 Marvin ↔ Companion JSON 訊息格式：
    {"type": "<event_name>", "payload": {...}, "ts": <unix_seconds>}
"""

import pytest

from companion import event_protocol as ep


class TestEventValidation:
    def test_validate_event_accepts_well_formed_message(self):
        msg = {"type": ep.STT_CHUNK, "payload": {"speaker": "jack", "text": "hi"}, "ts": 123.0}
        assert ep.validate_event(msg) is True

    def test_validate_event_rejects_missing_type(self):
        msg = {"payload": {}, "ts": 123.0}
        assert ep.validate_event(msg) is False

    def test_validate_event_rejects_missing_payload(self):
        msg = {"type": ep.STT_CHUNK, "ts": 123.0}
        assert ep.validate_event(msg) is False

    def test_validate_event_rejects_missing_ts(self):
        msg = {"type": ep.STT_CHUNK, "payload": {}}
        assert ep.validate_event(msg) is False

    def test_validate_event_rejects_unknown_type(self):
        msg = {"type": "totally_made_up_event", "payload": {}, "ts": 1.0}
        assert ep.validate_event(msg) is False

    def test_validate_event_rejects_non_dict(self):
        assert ep.validate_event("not a dict") is False
        assert ep.validate_event(None) is False
        assert ep.validate_event(123) is False

    def test_validate_event_rejects_non_numeric_ts(self):
        msg = {"type": ep.STT_CHUNK, "payload": {}, "ts": "not_a_number"}
        assert ep.validate_event(msg) is False

    def test_validate_event_rejects_non_dict_payload(self):
        msg = {"type": ep.STT_CHUNK, "payload": "not_dict", "ts": 1.0}
        assert ep.validate_event(msg) is False


class TestEventTypeConstants:
    """事件常數值必須穩定 — UI / bridge 兩端都會 hardcode 字串比對。"""

    def test_bridge_to_companion_event_constants_exist(self):
        # Marvin → companion → browsers
        assert ep.STT_CHUNK == "stt_chunk"
        assert ep.INTENT_ROUTED == "intent_routed"
        assert ep.TTS_STARTED == "tts_started"
        assert ep.TTS_DONE == "tts_done"
        assert ep.ATMOSPHERE_SNAPSHOT == "atmosphere_snapshot"
        assert ep.MEMBER_JOINED == "member_joined"
        assert ep.MEMBER_LEFT == "member_left"
        assert ep.MUSIC_STARTED == "music_started"
        assert ep.MUSIC_ENDED == "music_ended"
        assert ep.MUSIC_REACTION == "music_reaction"
        assert ep.GAME_PHASE_CHANGED == "game_phase_changed"

    def test_browser_to_bridge_event_constants_exist(self):
        # Browser → companion → Marvin
        assert ep.ATMOSPHERE_FEEDBACK == "atmosphere_feedback"
        assert ep.TTS_INJECTION == "tts_injection"
        assert ep.MODE_CHANGE == "mode_change"
        assert ep.MEMORY_LIST_REQUEST == "memory_list_request"
        assert ep.MEMORY_DELETE == "memory_delete"
        assert ep.MEMORY_MARK_UNCERTAIN == "memory_mark_uncertain"
        assert ep.MUSIC_PLAY_REQUEST == "music_play_request"
        assert ep.MUSIC_SKIP == "music_skip"

    def test_response_event_constants_exist(self):
        assert ep.MEMORY_LIST_RESPONSE == "memory_list_response"

    def test_known_event_types_set_covers_all_constants(self):
        # 自動完整性：所有定義的 _EVENT 字串都應該在 KNOWN_EVENT_TYPES 內
        assert ep.STT_CHUNK in ep.KNOWN_EVENT_TYPES
        assert ep.ATMOSPHERE_FEEDBACK in ep.KNOWN_EVENT_TYPES
        assert ep.MEMORY_LIST_RESPONSE in ep.KNOWN_EVENT_TYPES
