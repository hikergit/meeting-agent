"""
Screen adapter — captures the primary display and describes it with Gemini vision.

macOS: grant Screen Recording permission to Terminal in
  System Settings → Privacy & Security → Screen Recording
"""
import asyncio
import io
import logging
import os

import mss
from google import genai
from google.genai import types
from PIL import Image

from bus import bus
from contracts.observation import ObservationEvent

logger = logging.getLogger(__name__)

CAPTURE_INTERVAL = float(os.getenv("SCREEN_INTERVAL", "1.5"))
MODEL = "gemini-2.0-flash"  # vision, runs every ~1.5s — keep fast
MAX_DIM = 1024


def _capture() -> bytes:
    with mss.mss() as sct:
        mon = sct.monitors[1]
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        img.thumbnail((MAX_DIM, MAX_DIM))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        return buf.getvalue()


async def _describe(frame: bytes) -> str:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    img = Image.open(io.BytesIO(frame))
    resp = await asyncio.to_thread(
        client.models.generate_content,
        model=MODEL,
        contents=[
            "Describe what is visible on this screen in 1–3 concise sentences. "
            "Focus on key text, numbers, slide headings, and charts.",
            img,
        ],
    )
    return resp.text.strip()


async def run_screen_adapter() -> None:
    logger.info("Screen adapter running (interval=%.1fs)", CAPTURE_INTERVAL)
    last = ""
    while True:
        try:
            frame = await asyncio.to_thread(_capture)
            description = await _describe(frame)
            if description and description != last:
                obs = ObservationEvent(
                    type="screen",
                    source="screen_adapter",
                    speaker=None,
                    content=description,
                    raw={"bytes": len(frame)},
                )
                await bus.publish("observation", obs)
                last = description
                logger.debug("🖥  %s", description[:80])
        except Exception as e:
            logger.error("Screen adapter error: %s", e)
        await asyncio.sleep(CAPTURE_INTERVAL)
