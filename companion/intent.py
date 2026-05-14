"""語音指令意圖分類器（v1：純 regex，無 LLM）。

`classify_intent(text)` 將 STT 文字映射成 bridge 事件 payload。

回傳 shape：
    {
        "intent": str,         # "mode_silent" | ... | "unknown"
        "action": str | None,  # bridge 事件 type，例如 "mode_change"
        "payload": dict,       # 對應事件的 payload，unknown 為 {}
    }

設計原則：
- 純 regex，無 LLM 呼叫（v1 範圍）
- 中英文混合匹配，case-insensitive
- TTS_INJECTION 把觸發詞剝掉，剩下整段話當代言內容
"""

from __future__ import annotations

import re


# 觸發詞表：每個 intent 一組關鍵字 regex（含中英）。
# 順序很重要：先檢更具體的（mode_shutup 含「完全閉嘴」），再檢一般的（mode_silent 含「閉嘴」）。

# ── TTS 代言：trigger 後面的字串就是要說的內容 ────────────────────────────────
# 必須先檢，否則「跟大家說我太吵了」可能誤判成 too_loud。
_TTS_INJECT_TRIGGERS = [
    re.compile(r"^\s*跟大家說\s*", re.IGNORECASE),
    re.compile(r"^\s*幫我說\s*", re.IGNORECASE),
    re.compile(r"^\s*tell\s+them\s+", re.IGNORECASE),
    re.compile(r"^\s*say\s+", re.IGNORECASE),
]

# ── 模式：完全閉嘴（要比 silent 更具體，優先檢） ─────────────────────────────
_SHUTUP_RE = re.compile(
    r"完全閉嘴|別說了|不要再說|stop\s+talking\s+entirely|shut\s+up\s+completely",
    re.IGNORECASE,
)

# ── 模式：silent 5min ────────────────────────────────────────────────────────
_SILENT_RE = re.compile(
    r"閉嘴|安靜|別說話|不要說話|shut\s+up|be\s+quiet",
    re.IGNORECASE,
)

# ── 模式：serious ────────────────────────────────────────────────────────────
_SERIOUS_RE = re.compile(
    r"嚴肅|認真模式|serious\s+mode",
    re.IGNORECASE,
)

# ── 模式：resume / reset ─────────────────────────────────────────────────────
_RESUME_RE = re.compile(
    r"恢復|繼續|回來|resume|come\s+back",
    re.IGNORECASE,
)

# ── 氛圍回饋 ─────────────────────────────────────────────────────────────────
_TOO_LOUD_RE = re.compile(r"太吵|太多話|話太多|too\s+loud", re.IGNORECASE)
_TOO_SHARP_RE = re.compile(r"太刺|太諷刺|太尖|too\s+sharp|too\s+sarcastic", re.IGNORECASE)
_TOO_JOLLY_RE = re.compile(r"太嗨|太歡樂|別開玩笑了|too\s+jolly|stop\s+joking", re.IGNORECASE)


def _unknown() -> dict:
    return {"intent": "unknown", "action": None, "payload": {}}


def classify_intent(text: str) -> dict:
    """將語音文字分類為意圖事件。

    Args:
        text: STT 出來的純文字（可含標點）

    Returns:
        dict with keys: intent, action, payload
    """
    if not text or not text.strip():
        return _unknown()

    stripped = text.strip()

    # 1. TTS 代言（最優先：剝掉 trigger 後剩下整段話）
    for trig in _TTS_INJECT_TRIGGERS:
        m = trig.match(stripped)
        if m:
            rest = stripped[m.end():].strip()
            # 去尾標點（避免「我去吃飯了。」）
            rest = rest.rstrip("。.!！？?")
            if rest:
                return {
                    "intent": "tts_inject",
                    "action": "tts_injection",
                    "payload": {"text": rest, "voice": None, "target": None},
                }
            # 觸發詞後沒有內容 → unknown
            return _unknown()

    # 2. 完全閉嘴（比 silent 更強，要先檢）
    if _SHUTUP_RE.search(stripped):
        return {
            "intent": "mode_shutup",
            "action": "mode_change",
            "payload": {"mode": "shutup"},
        }

    # 3. 安靜 5 分鐘
    if _SILENT_RE.search(stripped):
        return {
            "intent": "mode_silent",
            "action": "mode_change",
            "payload": {"mode": "silent_5min"},
        }

    # 4. 嚴肅模式
    if _SERIOUS_RE.search(stripped):
        return {
            "intent": "mode_serious",
            "action": "mode_change",
            "payload": {"mode": "serious"},
        }

    # 5. 恢復 / reset
    if _RESUME_RE.search(stripped):
        return {
            "intent": "mode_resume",
            "action": "mode_change",
            "payload": {"mode": "reset"},
        }

    # 6. 氛圍回饋（三選一）
    if _TOO_LOUD_RE.search(stripped):
        return {
            "intent": "feedback_too_loud",
            "action": "atmosphere_feedback",
            "payload": {"label": "too_loud"},
        }
    if _TOO_SHARP_RE.search(stripped):
        return {
            "intent": "feedback_too_sharp",
            "action": "atmosphere_feedback",
            "payload": {"label": "too_sharp"},
        }
    if _TOO_JOLLY_RE.search(stripped):
        return {
            "intent": "feedback_too_jolly",
            "action": "atmosphere_feedback",
            "payload": {"label": "too_jolly"},
        }

    return _unknown()
