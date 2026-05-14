
## 語言規則

**所有回覆必須使用繁體中文。** 無論問題是什麼語言，一律以繁體中文回答。

---

## 專案定位

**Voice-bot-companion** 是 Marvin Discord Voice Bot 的控制 / 可視層，主要為作者本人使用。用途包括：
- 即時顯示 Marvin 的 STT、意圖判斷、TTS 佇列狀態（透過 WebSocket bridge）
- 校正氣氛讀判（🤐/🌶️/😄 三種事後回饋）
- Bubble 記憶編輯器 — 個人 profile + vector store 記憶可視化、可拖曳移除、可標疑
- 音樂 DJ 推薦面板（讀取 `music_memory.py`）
- 遊戲氛圍輔助（防呆雷達）
- 透過 Tailscale 從 iOS Safari 遠端控制

主專案路徑：`../Discord-voice-bot/`

---

## 與主專案的通訊架構

**架構選擇：WebSocket 雙向橋接**（2026-05-14 /plan-eng-review D1）

```
iOS Safari / Mac 瀏覽器
    ↕ WebSocket (透過 Tailscale)
companion-server (FastAPI, this repo)
    ↕ WebSocket (localhost)
companion_bridge.py (in marvin_voice_core/)
    ↕ direct import
Marvin (Discord-voice-bot process)
```

**不直接 import 主專案模組** — companion-server 與 Marvin 是兩個分離的 process，
透過 WebSocket 交換事件。companion_bridge.py 在 Marvin 端負責橋接，是少數會 import
主專案模組（AtmosphereTracker, VectorStore, MusicMemory）的位置。

**MarmoServer 仍然存在**，作為 NemoClaw → Marvin 的單向 webhook（`localhost:8765`）。
companion 不使用 MarmoServer — 它走自己的 WebSocket channel。

---

## TDD 開發模式（預設行為）

實作任何新功能或修 bug 時，**永遠先寫測試，再寫實作**。不需要用戶提醒。

### 流程

1. **寫失敗測試**：用 `tests/test_<feature>.py` 描述預期行為（assert 什麼、回傳什麼、狀態怎麼變）
2. **確認全紅**：執行 `pytest tests/test_<feature>.py`，確認所有測試都失敗（這證明測試有意義）
3. **寫最小實作**：只寫讓測試通過所需的程式碼，不多也不少
4. **確認全綠**：執行 pytest，全部通過才算完成
5. **Commit**：測試與實作放同一個 commit

### 測試命名原則

- `test_<行為描述>_<預期結果>`，例如 `test_send_voice_command_returns_ok`
- 每個測試只驗證一件事
- Fallback / edge case 一定要有對應測試

### 這個專案的測試慣例

- 使用 `pytest` + `pytest-asyncio`
- HTTP 呼叫（MarmoServer）用 `aioresponses` 或 `unittest.mock.patch` mock
- DB 讀取用 `db_path=":memory:"` 或複製測試用 fixture
- 不測 UI 元件渲染細節，只測業務邏輯與回傳值

---

## Companion 設計理念（繼承自主專案）

**零鍵盤操作**：輔助功能最終必須能讓 Marvin 透過語音觸發，不得只能靠 CLI 或手動操作。

**優雅降級**：每一個外部呼叫（MarmoServer、Gemini API、外部服務）都必須有 fallback，不能因單一服務失敗中斷功能。

**介面邊界清楚**：
```
Companion module → MarmoServer POST → Marvin TTS queue
Companion module → marvin.db (read-only) → 分析/報告
Companion module → External API → 結果注入 Marvin
```

**不直接 import 主專案模組**：companion 透過 webhook 或檔案介面與主專案溝通，保持獨立部署能力。

---

## 與主專案的介接規範

### WebSocket bridge protocol

雙向事件流，JSON message：`{"type": "<event_name>", "payload": {...}, "ts": <unix_seconds>}`

**Marvin → companion（主動推送）：**
- `stt_chunk` — STT 完成：`{speaker, text, engine}`
- `intent_routed` — 意圖判斷：`{intent, query, target_user}`
- `tts_started` / `tts_done` — TTS 狀態：`{text, voice, target}`
- `atmosphere_snapshot` — 週期性氣氛：`AtmosphereSnapshot` 序列化
- `member_joined` / `member_left` — 頻道成員變動
- `music_started` / `music_ended` / `music_reaction` — 音樂事件
- `game_phase_changed` — 遊戲狀態機

**companion → Marvin（請求 / 控制）：**
- `atmosphere_feedback` — `{snapshot_ts, label: "too_loud"|"too_sharp"|"too_jolly"}`
- `tts_injection` — `{text, voice, target}` 代言
- `mode_change` — `{mode: "silent_5min"|"serious"|"shutup"|"reset"}`
- `memory_list_request` — `{speaker, guild_id, limit}` → 回 `memory_list_response`
- `memory_delete` / `memory_mark_uncertain` — `{doc_id}`
- `music_play_request` / `music_skip` — `{song_id_or_query, target}`
- `music_recommendations_request` — `{target_username?}`（None = 房間級）→ 回 `music_recommendations_response`：`{target, recommendations, user_taste, history}`
- `game_force_skip_round` — `{game}`（如 `"detective"`）：跳過當前回合
- `game_end` — `{game}`：強制結束目前遊戲

失敗策略：任何 WebSocket 連線中斷，companion-server 進入 disconnected 狀態並每 5 秒
重連；UI 顯示連線狀態。Marvin 端 bridge 同樣自動重連。

### 記憶資料存取

**所有讀寫透過 bridge，不直接讀檔。** companion 不打開 `marvin.db` 或 `.chroma_db/`。
- 個人 profile：`memory_list_request` 取回 `suki_memory` 結構化欄位
- Vector chunks：`memory_list_request` 包含 vector store 的 `get_all` 結果
- 修正：`memory_delete` / `memory_mark_uncertain` 觸發 `VectorStore.delete/update`

---

## 日誌規範

模組前綴統一：
- Companion core：`[Companion]`
- MarmoServer 客戶端：`[Marmo_Client]`
- DB 分析：`[DB_Reader]`

高頻輪詢路徑用 `count % N == 0` 降頻，避免 log 爆炸。

---

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
