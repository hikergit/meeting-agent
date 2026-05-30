"""
Side panel — FastAPI server that pushes the live conversation (heard / agent /
your replies) and detailed insights to a local browser UI over WebSocket.
Nothing is posted into the meeting.
"""
import json
import logging
from pathlib import Path
from typing import Awaitable, Callable, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from action import voice
from contracts.decision import DecisionEvent
from contracts.meeting_state import MeetingState

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_connections: list[WebSocket] = []

# Set by orchestrator: called when the user types a reply in the panel.
# Signature: (agent_said: str, user_said: str) -> agent_reply: str
_reply_handler: Optional[Callable[[str, str], Awaitable[str]]] = None
# Set by orchestrator: called when the user requests meeting notes. Returns dict.
_notes_handler: Optional[Callable[[], Awaitable[dict]]] = None


@app.get("/")
async def index():
    return HTMLResponse((STATIC_DIR / "index.html").read_text())


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _connections.append(ws)
    logger.info("Panel client connected (%d total)", len(_connections))
    try:
        while True:
            raw = await ws.receive_text()
            await _handle_inbound(raw)
    except WebSocketDisconnect:
        if ws in _connections:
            _connections.remove(ws)


async def _handle_inbound(raw: str) -> None:
    """User typed a reply in the panel → generate the agent's response."""
    try:
        msg = json.loads(raw)
    except Exception:
        return
    if msg.get("type") == "gen_notes":
        if not _notes_handler:
            return
        await _broadcast(json.dumps({"type": "notes_pending"}))
        result = await _notes_handler()
        await _broadcast(json.dumps({"type": "notes", "data": result}))
        return

    if msg.get("type") != "user_reply" or not _reply_handler:
        return
    user_said = (msg.get("text") or "").strip()
    agent_said = msg.get("in_reply_to") or ""
    if not user_said:
        return
    # Echo the user's turn so every connected panel stays in sync.
    await _broadcast(json.dumps({"type": "you", "text": user_said}))
    reply = await _reply_handler(agent_said, user_said)
    await _broadcast(json.dumps({"type": "agent_reply", "text": reply}))
    await voice.speak(reply)


async def _broadcast(msg: str) -> None:
    dead = []
    for ws in list(_connections):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _connections:
            _connections.remove(ws)


async def broadcast_decision(decision: DecisionEvent) -> None:
    d = decision.model_dump()
    await _broadcast(json.dumps({"type": "decision", "data": d}))
    # Speak agent reactions that need attention (questions + high urgency).
    p = decision.payload
    if decision.urgency == "high" or p.title.lower().startswith(("suggested question", "🔧")):
        await voice.speak(f"{p.title}. {p.body}")


async def broadcast_heard(speaker: Optional[str], text: str) -> None:
    await _broadcast(json.dumps({"type": "heard", "speaker": speaker, "text": text}))


async def broadcast_state(state: MeetingState) -> None:
    await _broadcast(json.dumps({"type": "state", "data": state.model_dump()}))


def register(state: MeetingState, reply_handler: Optional[Callable] = None,
             notes_handler: Optional[Callable] = None) -> None:
    global _reply_handler, _notes_handler
    _reply_handler = reply_handler
    _notes_handler = notes_handler
    from bus import bus
    bus.subscribe("decision", broadcast_decision)


async def run_server(host: str = "0.0.0.0", port: int = 8765) -> None:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()
