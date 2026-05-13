
## 語言規則

**所有回覆必須使用繁體中文。** 無論問題是什麼語言，一律以繁體中文回答。

---

## 專案定位

**Voice-bot-companion** 是 Marvin Discord Voice Bot 的輔助/擴充模組集合，用途包括：
- 透過 MarmoServer webhook（`localhost:8765`）向 Marvin 注入語音指令或文字
- 讀取 `marvin.db`（SQLite）分析社群記憶與行為數據
- 實作獨立工具（管理 dashboard、排程任務、外部 API 橋接）供 Marvin 呼叫
- Landing page 或 companion web UI

主專案路徑：`../Discord-voice-bot/`  
MarmoServer webhook：`http://localhost:8765`（`MARMO_TOKEN` 驗證）

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

### MarmoServer webhook

```python
POST http://localhost:8765
Headers: Authorization: Bearer <MARMO_TOKEN>
Body: {"text": "要說的話", "voice": "en-US-GuyNeural"}
```

成功回傳 `{"status": "queued"}`；失敗時 companion 必須記 log，不得 raise 讓上層崩潰。

### marvin.db 讀取

- 路徑由環境變數 `MARVIN_DB_PATH` 指定，預設 `../Discord-voice-bot/marvin.db`
- **只讀**，不得在 companion 端寫入 marvin.db
- 讀取前確認檔案存在，不存在時 graceful fallback（回傳空資料，不 raise）

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
