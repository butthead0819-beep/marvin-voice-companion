"""語音指令意圖分類器（v1：純 regex，無 LLM）。

對應 Lane G 範圍：classify_intent(text) → {intent, action, payload}
"""

from companion.intent import classify_intent


# ── 模式切換 ─────────────────────────────────────────────────────────────────

def test_classify_intent_silent():
    """「閉嘴五分鐘」 → mode_silent。"""
    res = classify_intent("閉嘴五分鐘")
    assert res["intent"] == "mode_silent"
    assert res["action"] == "mode_change"
    assert res["payload"] == {"mode": "silent_5min"}


def test_classify_intent_silent_variant_quiet():
    """「安靜」也算 silent。"""
    res = classify_intent("安靜一下")
    assert res["intent"] == "mode_silent"


def test_classify_intent_serious():
    """「嚴肅模式」 → mode_serious。"""
    res = classify_intent("嚴肅模式")
    assert res["intent"] == "mode_serious"
    assert res["action"] == "mode_change"
    assert res["payload"] == {"mode": "serious"}


def test_classify_intent_resume():
    """「恢復」 → mode_resume → reset。"""
    res = classify_intent("好了恢復吧")
    assert res["intent"] == "mode_resume"
    assert res["action"] == "mode_change"
    assert res["payload"] == {"mode": "reset"}


def test_classify_intent_shutup():
    """「完全閉嘴」 → mode_shutup。"""
    res = classify_intent("完全閉嘴")
    assert res["intent"] == "mode_shutup"
    assert res["action"] == "mode_change"
    assert res["payload"] == {"mode": "shutup"}


# ── 氛圍回饋 ─────────────────────────────────────────────────────────────────

def test_classify_intent_too_loud():
    """「太吵了」 → feedback_too_loud。"""
    res = classify_intent("太吵了")
    assert res["intent"] == "feedback_too_loud"
    assert res["action"] == "atmosphere_feedback"
    assert res["payload"] == {"label": "too_loud"}


def test_classify_intent_too_sharp():
    """「太刺」 → feedback_too_sharp。"""
    res = classify_intent("太諷刺了")
    assert res["intent"] == "feedback_too_sharp"
    assert res["payload"] == {"label": "too_sharp"}


def test_classify_intent_too_jolly():
    """「太嗨」 → feedback_too_jolly。"""
    res = classify_intent("太嗨了")
    assert res["intent"] == "feedback_too_jolly"
    assert res["payload"] == {"label": "too_jolly"}


# ── TTS 代言 ─────────────────────────────────────────────────────────────────

def test_classify_intent_tts_inject():
    """「跟大家說我去吃飯了」 → tts_inject, text="我去吃飯了"。"""
    res = classify_intent("跟大家說我去吃飯了")
    assert res["intent"] == "tts_inject"
    assert res["action"] == "tts_injection"
    assert res["payload"]["text"] == "我去吃飯了"


def test_classify_intent_tts_inject_english():
    """「tell them I will be back」 → tts_inject。"""
    res = classify_intent("Tell them I will be back")
    assert res["intent"] == "tts_inject"
    assert res["payload"]["text"].strip().lower() == "i will be back"


# ── 英文指令至少一個跑得通 ────────────────────────────────────────────────────

def test_english_commands_shut_up():
    """「shut up」 → mode_silent。"""
    res = classify_intent("shut up")
    assert res["intent"] == "mode_silent"


def test_english_commands_serious():
    """英文「serious mode」 → mode_serious。"""
    res = classify_intent("serious mode")
    assert res["intent"] == "mode_serious"


# ── unknown fallback ─────────────────────────────────────────────────────────

def test_classify_intent_unknown():
    """隨機文字 → unknown。"""
    res = classify_intent("今天天氣不錯")
    assert res["intent"] == "unknown"
    assert res["action"] is None
    assert res["payload"] == {}


def test_classify_intent_empty_text_unknown():
    """空字串 → unknown。"""
    res = classify_intent("")
    assert res["intent"] == "unknown"
