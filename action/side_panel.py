"""
Side panel — FastAPI server that pushes DecisionEvents and MeetingState
to a local browser UI over WebSocket.
Nothing is posted into the meeting.
"""
import json
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from contracts.decision import DecisionEvent
from contracts.meeting_state import MeetingState

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_connections: list[WebSocket] = []


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
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in _connections:
            _connections.remove(ws)


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
    await _broadcast(json.dumps({"type": "decision", "data": decision.model_dump()}))


async def broadcast_state(state: MeetingState) -> None:
    await _broadcast(json.dumps({"type": "state", "data": state.model_dump()}))


def register(state: MeetingState) -> None:
    from bus import bus
    bus.subscribe("decision", broadcast_decision)


async def run_server(host: str = "0.0.0.0", port: int = 8765) -> None:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()
