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
    backend = os.getenv("PLANNING_BACKEND", "auto").lower()
    if not mock:
        log_backend()

    # Gemini backend: bootstrap managed agents once at startup (idempotent)
    managed_ids = None
    if backend == "gemini" and not mock:
        from planning.managed_agents import ensure_specialists
        managed_ids = await ensure_specialists()
        logger.info("Managed agents ready: %s", managed_ids)

    orchestrator = Orchestrator(managed_agent_ids=managed_ids)
    bus.subscribe("observation", orchestrator.handle_observation)
    register(orchestrator.state)

    tasks = [
        run_server(port=8765),
        run_caption_adapter(),
        _state_loop(orchestrator),
    ]
    if os.getenv("ENABLE_SCREEN", "true").lower() == "true":
        tasks.append(run_screen_adapter())
    else:
        logger.info("Screen adapter disabled (ENABLE_SCREEN=false)")

    logger.info("Meeting Copilot live — open http://localhost:8765")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
