"""
Screen adapter — captures primary display, describes it via LLM vision.
macOS: grant Screen Recording to Terminal in System Settings → Privacy & Security.
"""
import asyncio
import io
import logging
import os

import mss
from PIL import Image

from bus import bus
from contracts.observation import ObservationEvent

logger = logging.getLogger(__name__)

CAPTURE_INTERVAL = float(os.getenv("SCREEN_INTERVAL", "1.5"))


def _capture() -> bytes:
    with mss.mss() as sct:
        mon = sct.monitors[1]
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        img.thumbnail((1024, 1024))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        return buf.getvalue()


async def _describe(frame: bytes) -> str:
    backend = os.getenv("PLANNING_BACKEND", "auto").lower()
    if backend == "auto":
        backend = "claude" if os.getenv("ANTHROPIC_API_KEY") else "gemini"

    if backend == "claude":
        import anthropic, base64
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        def _call():
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(frame).decode()}},
                    {"type": "text", "text": "Describe what is on this screen in 1–3 concise sentences. Focus on key text, numbers, slide headings, charts."},
                ]}],
            )
            return msg.content[0].text
        return await asyncio.to_thread(_call)
    else:
        from google import genai
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        img = Image.open(io.BytesIO(frame))
        def _call():
            resp = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=["Describe what is on this screen in 1–3 concise sentences. Focus on key text, numbers, slide headings, charts.", img],
            )
            return resp.text.strip()
        return await asyncio.to_thread(_call)


async def run_screen_adapter() -> None:
    logger.info("Screen adapter running (interval=%.1fs)", CAPTURE_INTERVAL)
    last = ""
    while True:
        try:
            frame = await asyncio.to_thread(_capture)
            description = await _describe(frame)
            if description and description != last:
                obs = ObservationEvent(
                    type="screen", source="screen_adapter",
                    speaker=None, content=description,
                    raw={"bytes": len(frame)},
                )
                await bus.publish("observation", obs)
                last = description
                logger.debug("🖥  %s", description[:80])
        except Exception as e:
            logger.error("Screen adapter error: %s", e)
        await asyncio.sleep(CAPTURE_INTERVAL)
