"""
Meeting Copilot — live mode.
Starts all perception adapters, the planning orchestrator, and the side panel server.

Open http://localhost:8765 in a browser to see the side panel.
"""
import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from action.side_panel import broadcast_state, register, run_server
from bus import bus
from perception.caption_adapter import run_caption_adapter
from perception.screen_adapter import run_screen_adapter
from planning.orchestrator import Orchestrator
from planning.llm import log_backend

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-28s %(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)


async def _state_loop(orchestrator: Orchestrator) -> None:
    while True:
        await broadcast_state(orchestrator.state)
        await asyncio.sleep(2)


async def main() -> None:
    mock = os.getenv("MOCK_PLANNING", "false").lower() == "true"
    if not mock:
        log_backend()

    orchestrator = Orchestrator()
    bus.subscribe("observation", orchestrator.handle_observation)
    register(orchestrator.state)

    logger.info("Meeting Copilot live — open http://localhost:8765")
    await asyncio.gather(
        run_server(port=8765),
        run_caption_adapter(),
        run_screen_adapter(),
        _state_loop(orchestrator),
    )


if __name__ == "__main__":
    asyncio.run(main())
