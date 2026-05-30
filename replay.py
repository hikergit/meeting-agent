"""
Demo fallback / test harness — replays perception/sample_stream.json through the
full planning + action stack without needing a live meeting or Chrome.

Usage:
  python replay.py                  # 2s between events (default)
  python replay.py --interval 0.5   # fast replay for testing
  python replay.py --interval 0     # instant (stress test)

Open http://localhost:8765 to watch the side panel update in real time.
"""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from action.side_panel import broadcast_state, register, run_server
from bus import bus
from contracts.observation import ObservationEvent
from planning.orchestrator import Orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-28s %(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)

STREAM = Path(__file__).parent / "perception" / "sample_stream.json"


async def _replay(interval: float) -> None:
    events = json.loads(STREAM.read_text())
    logger.info("Replaying %d observations (interval=%.1fs) …", len(events), interval)
    for raw in events:
        obs = ObservationEvent(**raw)
        logger.info("▶ [%-10s] %s", obs.type, obs.content[:70])
        await bus.publish("observation", obs)
        if interval > 0:
            await asyncio.sleep(interval)
    logger.info("✓ Replay complete")


async def _state_loop(orchestrator: Orchestrator) -> None:
    while True:
        await broadcast_state(orchestrator.state)
        await asyncio.sleep(2)


async def main(interval: float) -> None:
    mock = os.getenv("MOCK_PLANNING", "false").lower() == "true"
    if not mock and not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY not set — or run with MOCK_PLANNING=true")

    orchestrator = Orchestrator()
    bus.subscribe("observation", orchestrator.handle_observation)
    register(orchestrator.state, reply_handler=orchestrator.handle_user_reply,
                 notes_handler=orchestrator.generate_notes)

    logger.info("Side panel → http://localhost:8765")
    await asyncio.gather(
        run_server(port=8765),
        _replay(interval),
        _state_loop(orchestrator),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between observations")
    args = parser.parse_args()
    asyncio.run(main(args.interval))
