"""FastAPI server — companion-server 的 WebSocket hub。

職責（注意：零業務邏輯）：
- 靜態檔案：GET / 回 static/index.html、GET /static/* 直接送檔
- WS /ws：瀏覽器（Mac + iPhone）連進來，雙向中繼到 bridge
- 啟動時起 BridgeClient（mock 或 real），bridge → all browsers 廣播
- 斷線清理：瀏覽器 disconnect → 從 registry 移除
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional

import aiohttp
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from companion.bridge_client import BridgeClient
from companion.event_protocol import (
    BROWSER_TO_BRIDGE_EVENTS,
    validate_event,
)
from companion.intent import classify_intent

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"

GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_STT_MODEL = "whisper-large-v3-turbo"


async def _call_groq_stt(file_path: str, api_key: str) -> str:
    """呼叫 Groq Whisper STT，回傳轉錄文字。

    Args:
        file_path: 暫存音檔絕對路徑
        api_key: Groq API key

    Returns:
        轉錄出來的純文字（去頭尾空白）。失敗則回傳空字串。
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        with open(file_path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field("file", f, filename=Path(file_path).name, content_type="audio/webm")
            data.add_field("model", GROQ_STT_MODEL)
            data.add_field("response_format", "json")
            async with session.post(GROQ_STT_URL, headers=headers, data=data) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("[Companion] Groq STT 失敗 status=%s body=%s", resp.status, body[:200])
                    return ""
                payload = await resp.json()
                return (payload.get("text") or "").strip()


def create_app(bridge: Optional[BridgeClient] = None) -> FastAPI:
    """工廠：建立 FastAPI app。

    bridge 可由外部傳入（測試常用 mock_mode 的 instance）；不傳則自動建一個 real-mode。
    """
    _bridge = bridge or BridgeClient.from_env()

    @asynccontextmanager
    async def lifespan(fa: FastAPI):
        await fa.state.bridge.start()
        logger.info("[Companion] server startup complete")
        try:
            yield
        finally:
            for cid, ws in list(fa.state.clients.items()):
                try:
                    await ws.close()
                except Exception:
                    pass
            fa.state.clients.clear()
            await fa.state.bridge.stop()
            logger.info("[Companion] server shutdown complete")

    app = FastAPI(lifespan=lifespan)
    app.state.bridge = _bridge
    app.state.clients: Dict[str, WebSocket] = {}

    # ---------- bridge → browsers 廣播 handler ----------
    async def _broadcast_to_browsers(event: dict) -> None:
        # 防呆：bridge 端理論上送合規格事件；不合規就 drop + log
        if not validate_event(event):
            logger.warning("[Companion] dropped invalid bridge event: %s", event)
            return
        dead = []
        for cid, ws in list(app.state.clients.items()):
            try:
                await ws.send_json(event)
            except Exception as exc:
                logger.warning("[Companion] broadcast to %s failed: %s", cid, exc)
                dead.append(cid)
        for cid in dead:
            app.state.clients.pop(cid, None)

    app.state.bridge.on_event(_broadcast_to_browsers)

    # ---------- HTTP routes ----------
    @app.get("/")
    async def root():
        if INDEX_HTML.exists():
            return FileResponse(str(INDEX_HTML))
        # Fallback：static 還沒被填滿時也要能回應
        return HTMLResponse("<html><body>Companion connecting…</body></html>")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ---------- POST /audio：PTT 音檔上傳 → Groq STT → 意圖分類 → bridge ----------
    @app.post("/audio")
    async def upload_audio(audio: UploadFile = File(...)):
        """接收 webm/opus（或 mp4）音檔，呼叫 Groq STT，分類意圖並 forward 到 bridge。

        回傳：`{text, engine, intent, action, payload}`
        失敗：
        - 缺 GROQ_API_KEY → 503
        - Groq 呼叫失敗 → text 空字串 + intent="unknown"
        """
        api_key = (os.getenv("GROQ_API_KEY") or "").strip()
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="GROQ_API_KEY 未設定，無法執行語音轉文字。請在 .env 補上後重啟。",
            )

        # 先把上傳檔寫入暫存檔，finally 一定清掉
        suffix = ".webm"
        ct = (audio.content_type or "").lower()
        if "mp4" in ct or "m4a" in ct or "aac" in ct:
            suffix = ".mp4"
        elif "ogg" in ct:
            suffix = ".ogg"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp_path = tmp.name
        try:
            content = await audio.read()
            tmp.write(content)
            tmp.close()

            text = await _call_groq_stt(tmp_path, api_key)
            result = classify_intent(text)
            intent = result["intent"]
            action = result["action"]
            payload = result["payload"]

            # 非 unknown → forward 到 bridge
            if intent != "unknown" and action:
                evt = {"type": action, "payload": payload, "ts": time.time()}
                try:
                    await app.state.bridge.send(evt)
                except Exception as exc:
                    logger.warning("[Companion] bridge.send failed: %s", exc)

            return {
                "text": text,
                "engine": "Groq",
                "intent": intent,
                "action": action,
                "payload": payload,
            }
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    # ---------- WebSocket ----------
    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        client_id = uuid.uuid4().hex[:8]
        app.state.clients[client_id] = websocket
        logger.info("[Companion] browser connected id=%s (total=%d)", client_id, len(app.state.clients))
        try:
            while True:
                msg = await websocket.receive_json()
                await _handle_browser_message(app, msg)
        except WebSocketDisconnect:
            logger.info("[Companion] browser disconnected id=%s", client_id)
        except Exception as exc:
            logger.warning("[Companion] ws error id=%s: %s", client_id, exc)
        finally:
            app.state.clients.pop(client_id, None)

    return app


async def _handle_browser_message(app: FastAPI, msg: dict) -> None:
    """瀏覽器 → companion → bridge 的路由邏輯。

    - 不合規 shape：log 後 drop
    - 已知 browser→bridge 事件：forward
    - 其他（bridge→browser 事件從瀏覽器送來、或未知 type）：log 後 drop
    """
    if not validate_event(msg):
        logger.warning("[Companion] dropped invalid browser msg: %s", msg)
        return
    evt_type = msg["type"]
    if evt_type not in BROWSER_TO_BRIDGE_EVENTS:
        logger.warning("[Companion] dropped non-browser-side event: type=%s", evt_type)
        return
    await app.state.bridge.send(msg)


# 預設 app（uvicorn companion.server:app 用）
app = create_app()
