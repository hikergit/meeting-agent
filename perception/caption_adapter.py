"""
Caption adapter — reads Google Meet live captions via Chrome DevTools Protocol.

Requirements:
  1. Launch Chrome with: --remote-debugging-port=9222
  2. Open meet.google.com and turn captions ON
  3. macOS: grant Screen Recording permission to Chrome (System Settings → Privacy)

The JS selector is brittle to Meet DOM changes — verify/update on demo day.
"""
import asyncio
import json
import logging
import os
from typing import Optional

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from bus import bus
from contracts.observation import ObservationEvent, Speaker

logger = logging.getLogger(__name__)

CDP_HTTP = "http://localhost:9222"
POLL_INTERVAL = 0.5  # seconds

# Extracts caption lines from the Meet DOM.
# Tries multiple selector strategies so it survives minor Meet updates.
# Verify this on demo day — Meet obfuscates class names and they change.
_CAPTION_JS = r"""
(function () {
  const results = [];

  // Verified against live Meet DOM (May 2026):
  //   [aria-label="Captions"]  → caption container
  //     .nMcdL                 → one row per speaker turn
  //       .NWpY1d / .adE6rb    → speaker name
  //       .ygicle / .VbkSUe    → spoken text
  const container = document.querySelector('[aria-label="Captions"]');
  if (container) {
    container.querySelectorAll('.nMcdL').forEach(row => {
      const nameEl = row.querySelector('.NWpY1d') || row.querySelector('.adE6rb');
      const textEl = row.querySelector('.ygicle') || row.querySelector('.VbkSUe');
      const text = textEl?.textContent?.trim();
      let name = nameEl?.textContent?.trim() || null;
      if (name === 'You') name = '__SELF__';  // resolve to real name downstream
      if (text) results.push({ name, text });
    });
  }

  return JSON.stringify(results);
})()
"""


async def _find_meet_tab() -> Optional[str]:
    pattern = os.getenv("MEET_TAB_URL", "meet.google.com")
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{CDP_HTTP}/json")
            for tab in resp.json():
                if pattern in tab.get("url", ""):
                    return tab["webSocketDebuggerUrl"]
    except Exception as e:
        logger.debug("CDP tab lookup failed: %s", e)
    return None


async def run_caption_adapter() -> None:
    ws_url: Optional[str] = None
    msg_id = 0
    self_name = os.getenv("SELF_NAME", "Me")

    # Meet captions grow incrementally per speaker turn. We track the latest text
    # per speaker and only EMIT a line once it has stopped changing for
    # STABLE_TICKS polls (i.e. the speaker finished that utterance).
    STABLE_TICKS = 3
    pending: dict[str, dict] = {}   # name -> {"text": str, "stable": int}
    emitted: set[str] = set()

    logger.info("Caption adapter: waiting for Meet tab on CDP :9222")

    while True:
        try:
            if not ws_url:
                ws_url = await _find_meet_tab()
                if not ws_url:
                    logger.warning(
                        "No Meet tab found — open meet.google.com and launch Chrome "
                        "with --remote-debugging-port=9222"
                    )
                    await asyncio.sleep(5)
                    continue
                logger.info("Caption adapter connected to Meet tab")

            async with websockets.connect(
                ws_url,
                additional_headers={"Origin": "http://localhost:9222"}
            ) as ws:
                while True:
                    msg_id += 1
                    await ws.send(json.dumps({
                        "id": msg_id,
                        "method": "Runtime.evaluate",
                        "params": {"expression": _CAPTION_JS, "returnByValue": True},
                    }))
                    raw = json.loads(await ws.recv())
                    value = raw.get("result", {}).get("result", {}).get("value", "[]")
                    lines: list[dict] = json.loads(value)

                    current = {}
                    for line in lines:
                        name = line.get("name") or "unknown"
                        if name == "__SELF__":
                            name = self_name
                        current[name] = line["text"]

                    # Advance stability counters
                    for name, text in current.items():
                        p = pending.get(name)
                        if p and p["text"] == text:
                            p["stable"] += 1
                        else:
                            pending[name] = {"text": text, "stable": 0}

                    # Emit lines that have stabilized and not yet been emitted
                    for name, p in list(pending.items()):
                        key = f"{name}||{p['text']}"
                        if p["stable"] >= STABLE_TICKS and key not in emitted and p["text"]:
                            emitted.add(key)
                            obs = ObservationEvent(
                                type="transcript",
                                source="caption_adapter",
                                speaker=Speaker(id=name, name=name),
                                content=p["text"],
                                raw={"name": name},
                            )
                            await bus.publish("observation", obs)
                            logger.info("📝 %s: %s", name, p["text"][:70])

                    await asyncio.sleep(POLL_INTERVAL)

        except (ConnectionClosed, OSError) as e:
            logger.warning("Caption adapter lost connection: %s — reconnecting", e)
            ws_url = None
            await asyncio.sleep(3)
        except Exception as e:
            logger.error("Caption adapter error: %s", e)
            ws_url = None
            await asyncio.sleep(5)
