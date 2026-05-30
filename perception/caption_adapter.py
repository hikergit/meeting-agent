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

  // Strategy 1: data-participant-id containers (Meet 2024+)
  document.querySelectorAll('[data-participant-id]').forEach(p => {
    const text = p.querySelector('[jsname="YSxPC"], [data-message-text]');
    const name = p.querySelector('[data-self-name], [jsname="r4nke"]');
    if (text?.textContent?.trim()) {
      results.push({ name: name?.textContent?.trim() || null, text: text.textContent.trim() });
    }
  });

  // Strategy 2: aria-live region (fallback)
  if (!results.length) {
    document.querySelectorAll('[aria-live="polite"] span, [aria-live="assertive"] span').forEach(el => {
      const t = el.textContent.trim();
      if (t.length > 4) results.push({ name: null, text: t });
    });
  }

  return JSON.stringify(results);
})()
"""


async def _find_meet_tab() -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{CDP_HTTP}/json")
            for tab in resp.json():
                if "meet.google.com" in tab.get("url", ""):
                    return tab["webSocketDebuggerUrl"]
    except Exception as e:
        logger.debug("CDP tab lookup failed: %s", e)
    return None


async def run_caption_adapter() -> None:
    seen: set[str] = set()
    ws_url: Optional[str] = None
    msg_id = 0

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

                    for line in lines:
                        key = f"{line.get('name')}||{line.get('text')}"
                        if key not in seen:
                            seen.add(key)
                            obs = ObservationEvent(
                                type="transcript",
                                source="caption_adapter",
                                speaker=Speaker(
                                    id=line.get("name") or "unknown",
                                    name=line.get("name"),
                                ),
                                content=line["text"],
                                raw=line,
                            )
                            await bus.publish("observation", obs)
                            logger.debug("📝 %s: %s", line.get("name", "?"), line["text"][:60])

                    await asyncio.sleep(POLL_INTERVAL)

        except (ConnectionClosed, OSError) as e:
            logger.warning("Caption adapter lost connection: %s — reconnecting", e)
            ws_url = None
            await asyncio.sleep(3)
        except Exception as e:
            logger.error("Caption adapter error: %s", e)
            ws_url = None
            await asyncio.sleep(5)
