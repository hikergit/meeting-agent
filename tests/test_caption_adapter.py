"""
End-to-end test of the caption adapter against a local Meet simulator page.

Run:
  1. Start Chrome with: python3.11 tests/test_caption_adapter.py
     (it launches Chrome automatically)
  2. Watch for captured caption observations in stdout.

This validates the full pipeline:
  Chrome DevTools → caption JS → ObservationEvent → bus → planning → side panel
"""
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SIM_PORT = 8766
os.environ["MEET_TAB_URL"] = f"localhost:{SIM_PORT}"  # must be set before import

from bus import bus
from contracts.observation import ObservationEvent
from perception.caption_adapter import run_caption_adapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("test")

CDP_PORT = 9222
SIM_URL = f"http://localhost:{SIM_PORT}/meet_simulator.html"
SIM_DIR = os.path.dirname(os.path.abspath(__file__))

# Tell caption adapter to look for our simulator URL instead of meet.google.com
os.environ["MEET_TAB_URL"] = f"localhost:{SIM_PORT}"


def launch_chrome():
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    subprocess.Popen([
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-allow-origins=http://localhost:9222",
        "--user-data-dir=/tmp/chrome-caption-test",
        "--no-first-run", "--no-default-browser-check",
        SIM_URL,
    ], stderr=subprocess.DEVNULL)
    time.sleep(4)


def start_http_server():
    import http.server, threading
    handler = http.server.SimpleHTTPRequestHandler
    httpd = http.server.HTTPServer(("", SIM_PORT), handler)
    httpd.allow_reuse_address = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    os.chdir(SIM_DIR)
    return httpd


def inject_captions():
    """Inject test caption lines into the simulator page via CDP."""
    import websockets

    async def _inject():
        tabs = json.loads(urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json").read())
        tab = next((t for t in tabs if "meet_simulator" in t.get("url", "")), None)
        if not tab:
            logger.error("Simulator tab not found — check Chrome launched correctly")
            return

        async with websockets.connect(
            tab["webSocketDebuggerUrl"],
            additional_headers={"Origin": f"http://localhost:{CDP_PORT}"}
        ) as ws:
            lines = [
                ("Speaker One", "This is a caption adapter test line one."),
                ("Speaker Two", "Testing speaker attribution on the second line."),
                ("Speaker One", "A third line to confirm dedup and ordering."),
                ("Speaker Two", "Final test line for the caption pipeline."),
            ]
            for speaker, text in lines:
                js = f"addLine({json.dumps(speaker)}, {json.dumps(text)})"
                await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": js}}))
                await ws.recv()
                logger.info("Injected: %s: %s", speaker, text)
                await asyncio.sleep(1.5)

    asyncio.run(_inject())


async def main():
    logger.info("Starting HTTP server for simulator...")
    start_http_server()
    logger.info("Launching Chrome with simulator page...")
    launch_chrome()

    # Collect observations
    seen = []
    async def on_obs(obs: ObservationEvent):
        seen.append(obs)
        logger.info("✓ OBSERVATION [%s] %s: %s", obs.type, obs.speaker and obs.speaker.name, obs.content[:60])

    bus.subscribe("observation", on_obs)

    # Inject captions in background then let adapter run
    inject_task = asyncio.create_task(asyncio.to_thread(inject_captions))
    adapter_task = asyncio.create_task(run_caption_adapter())

    # Run for 15 seconds
    await asyncio.sleep(15)
    adapter_task.cancel()
    await inject_task

    print(f"\n{'='*50}")
    print(f"RESULT: captured {len(seen)} observations")
    for o in seen:
        print(f"  [{o.type}] {o.speaker and o.speaker.name}: {o.content[:80]}")

    if len(seen) >= 3:
        print("\n✅ Caption adapter working end-to-end with Chrome DevTools")
    else:
        print(f"\n❌ Expected ≥3 observations, got {len(seen)}")

    # Cleanup
    subprocess.run(["pkill", "-f", "Google Chrome.*9222"], capture_output=True)


if __name__ == "__main__":
    asyncio.run(main())
