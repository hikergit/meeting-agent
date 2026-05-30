"""
Screen adapter — captures the primary display and describes it with Gemini vision.

macOS requirement: grant Screen Recording permission to Terminal/iTerm in
  System Settings → Privacy & Security → Screen Recording
"""
import asyncio
import io
import logging
import os

import google.generativeai as genai
import mss
from PIL import Image

from bus import bus
from contracts.observation import ObservationEvent

logger = logging.getLogger(__name__)

CAPTURE_INTERVAL = float(os.getenv("SCREEN_INTERVAL", "1.5"))
GEMINI_MODEL = "gemini-2.0-flash"  # vision, runs every ~1.5s — keep fast
MAX_DIM = 1024  # resize before sending; saves tokens


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
    img = Image.open(io.BytesIO(frame))
    model = genai.GenerativeModel(GEMINI_MODEL)
    resp = await asyncio.to_thread(
        model.generate_content,
        [
            "Describe what is visible on this screen in 1–3 concise sentences. "
            "Focus on key text, numbers, slide headings, and charts. Be precise.",
            img,
        ],
    )
    return resp.text.strip()


async def run_screen_adapter() -> None:
    logger.info("Screen adapter running (interval=%.1fs, model=%s)", CAPTURE_INTERVAL, GEMINI_MODEL)
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
