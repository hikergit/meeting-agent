"""
Screen adapter — turns what's on screen into `screen` observations via Gemini vision.

Two capture sources (SCREEN_SOURCE env):
  "cdp" (default) — screenshot the Meet browser tab over Chrome DevTools. This
      captures exactly what the meeting shows, INCLUDING a participant's shared
      screen (it renders in the page). No macOS Screen Recording permission, no
      desktop noise. Reuses the same CDP connection as the caption adapter.
  "display" — full primary monitor via mss. Works for in-room/non-Meet setups
      but needs macOS Screen Recording permission and captures the whole desktop.
"""
import asyncio
import base64
import io
import json
import logging
import os
from typing import Optional

import httpx
import websockets

from bus import bus
from contracts.observation import ObservationEvent

logger = logging.getLogger(__name__)

CAPTURE_INTERVAL = float(os.getenv("SCREEN_INTERVAL", "2.0"))
SOURCE = os.getenv("SCREEN_SOURCE", "cdp").lower()
CDP_HTTP = "http://localhost:9222"
_MEET_URL = os.getenv("MEET_TAB_URL", "meet.google.com")


# ---- capture sources -------------------------------------------------------

def _capture_display() -> bytes:
    import mss
    from PIL import Image
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        img.thumbnail((1280, 1280))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        return buf.getvalue()


async def _find_meet_ws() -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            for tab in (await c.get(f"{CDP_HTTP}/json")).json():
                if _MEET_URL in tab.get("url", ""):
                    return tab["webSocketDebuggerUrl"]
    except Exception as e:
        logger.debug("CDP lookup failed: %s", e)
    return None


async def _capture_cdp(ws) -> Optional[bytes]:
    await ws.send(json.dumps({"id": 99, "method": "Page.captureScreenshot",
                              "params": {"format": "jpeg", "quality": 60}}))
    while True:
        r = json.loads(await ws.recv())
        if r.get("id") == 99:
            data = r.get("result", {}).get("data")
            return base64.b64decode(data) if data else None


# ---- vision ----------------------------------------------------------------

async def _describe(frame: bytes) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def _call():
        resp = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=[
                "This is a live meeting screen. Describe what is being shown or shared in "
                "1-3 sentences. Focus on slides, shared documents, code, charts, and any "
                "specific numbers or headings. If it's just the meeting grid with no shared "
                "content, say 'No shared content.'",
                types.Part.from_bytes(data=frame, mime_type="image/jpeg"),
            ],
        )
        return (resp.text or "").strip()

    return await asyncio.to_thread(_call)


# ---- run loop --------------------------------------------------------------

async def run_screen_adapter() -> None:
    logger.info("Screen adapter running (source=%s, interval=%.1fs)", SOURCE, CAPTURE_INTERVAL)
    last = ""

    if SOURCE == "display":
        while True:
            try:
                desc = await _describe(await asyncio.to_thread(_capture_display))
                last = await _emit(desc, last)
            except Exception as e:
                logger.error("Screen adapter (display) error: %s", e)
            await asyncio.sleep(CAPTURE_INTERVAL)
        return

    # CDP source: capture the Meet tab.
    while True:
        ws_url = await _find_meet_ws()
        if not ws_url:
            logger.warning("Screen adapter: no Meet tab on CDP — retrying")
            await asyncio.sleep(5)
            continue
        try:
            async with websockets.connect(ws_url, additional_headers={"Origin": "http://localhost:9222"}) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
                await ws.recv()
                logger.info("Screen adapter capturing Meet tab via CDP")
                while True:
                    frame = await _capture_cdp(ws)
                    if frame:
                        desc = await _describe(frame)
                        if desc and "no shared content" not in desc.lower():
                            last = await _emit(desc, last)
                    await asyncio.sleep(CAPTURE_INTERVAL)
        except (websockets.exceptions.ConnectionClosed, OSError) as e:
            logger.warning("Screen adapter CDP lost: %s — reconnecting", e)
            await asyncio.sleep(3)
        except Exception as e:
            logger.error("Screen adapter error: %s", e)
            await asyncio.sleep(5)


async def _emit(desc: str, last: str) -> str:
    if desc and desc != last:
        obs = ObservationEvent(
            type="screen", source="screen_adapter",
            speaker=None, content=desc, raw={"source": SOURCE},
        )
        await bus.publish("observation", obs)
        logger.info("🖥  %s", desc[:80])
        return desc
    return last
