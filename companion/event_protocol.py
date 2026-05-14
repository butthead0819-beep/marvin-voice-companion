"""事件協定常數與驗證 helper。

來源：CLAUDE.md 中定義的 Marvin ↔ Companion JSON 訊息：
    {"type": "<event_name>", "payload": {...}, "ts": <unix_seconds>}

本模組只負責定義常數與最低限度的 shape 驗證，不做業務邏輯。
"""

from __future__ import annotations

from typing import Any


# === Bridge → companion → browsers（Marvin 主動推送）===
STT_CHUNK = "stt_chunk"
INTENT_ROUTED = "intent_routed"
TTS_STARTED = "tts_started"
TTS_DONE = "tts_done"
ATMOSPHERE_SNAPSHOT = "atmosphere_snapshot"
MEMBER_JOINED = "member_joined"
MEMBER_LEFT = "member_left"
# Lane B2：新 client 連上時，bridge 立即推當前語音頻道成員快照
VOICE_CHANNEL_SNAPSHOT = "voice_channel_snapshot"
MUSIC_STARTED = "music_started"
MUSIC_ENDED = "music_ended"
MUSIC_REACTION = "music_reaction"
GAME_PHASE_CHANGED = "game_phase_changed"

# === Browser → companion → bridge（請求 / 控制）===
ATMOSPHERE_FEEDBACK = "atmosphere_feedback"
TTS_INJECTION = "tts_injection"
MODE_CHANGE = "mode_change"
MEMORY_LIST_REQUEST = "memory_list_request"
MEMORY_DELETE = "memory_delete"
MEMORY_MARK_UNCERTAIN = "memory_mark_uncertain"
MUSIC_PLAY_REQUEST = "music_play_request"
MUSIC_SKIP = "music_skip"
MUSIC_RECOMMENDATIONS_REQUEST = "music_recommendations_request"
GAME_FORCE_SKIP_ROUND = "game_force_skip_round"
GAME_END = "game_end"

# === Response 型別（bridge → browser，作為 request 的回應）===
MEMORY_LIST_RESPONSE = "memory_list_response"
MUSIC_RECOMMENDATIONS_RESPONSE = "music_recommendations_response"


BRIDGE_TO_BROWSER_EVENTS = frozenset(
    {
        STT_CHUNK,
        INTENT_ROUTED,
        TTS_STARTED,
        TTS_DONE,
        ATMOSPHERE_SNAPSHOT,
        MEMBER_JOINED,
        MEMBER_LEFT,
        VOICE_CHANNEL_SNAPSHOT,
        MUSIC_STARTED,
        MUSIC_ENDED,
        MUSIC_REACTION,
        GAME_PHASE_CHANGED,
        MEMORY_LIST_RESPONSE,
        MUSIC_RECOMMENDATIONS_RESPONSE,
    }
)

BROWSER_TO_BRIDGE_EVENTS = frozenset(
    {
        ATMOSPHERE_FEEDBACK,
        TTS_INJECTION,
        MODE_CHANGE,
        MEMORY_LIST_REQUEST,
        MEMORY_DELETE,
        MEMORY_MARK_UNCERTAIN,
        MUSIC_PLAY_REQUEST,
        MUSIC_SKIP,
        MUSIC_RECOMMENDATIONS_REQUEST,
        GAME_FORCE_SKIP_ROUND,
        GAME_END,
    }
)

KNOWN_EVENT_TYPES = BRIDGE_TO_BROWSER_EVENTS | BROWSER_TO_BRIDGE_EVENTS


def validate_event(msg: Any) -> bool:
    """檢查訊息是否符合 {type, payload, ts} 結構且 type 為已知。

    回傳 True 表示可安全路由；False 表示 caller 應該 drop 並 log。
    """
    if not isinstance(msg, dict):
        return False
    if "type" not in msg or "payload" not in msg or "ts" not in msg:
        return False
    if not isinstance(msg["payload"], dict):
        return False
    if not isinstance(msg["ts"], (int, float)) or isinstance(msg["ts"], bool):
        return False
    if msg["type"] not in KNOWN_EVENT_TYPES:
        return False
    return True
