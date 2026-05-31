"""
Meeting Copilot — live mode.
Starts all perception adapters, the planning orchestrator, and the side panel server.

Open http://localhost:8765 in a browser to see the side panel.
"""
import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()              # secrets from .env
from config import load_config
load_config()              # tunables from config.toml → env (before modules read them)

from action.side_panel import broadcast_state, register, run_server
from bus import bus
from perception.audio_adapter import run_audio_adapter
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

    # If the user chose the Gemini Managed Agents executor, pre-create the
    # specialist agents on Google's side. Default ("claude") skips this.
    managed_ids = None
    if os.getenv("EXECUTOR_BACKEND", "claude").lower() == "managed":
        from planning.managed_agents import ensure_specialists
        managed_ids = await ensure_specialists()

    orchestrator = Orchestrator(managed_agent_ids=managed_ids)
    bus.subscribe("observation", orchestrator.handle_observation)
    register(orchestrator.state, reply_handler=orchestrator.handle_user_reply,
                 notes_handler=orchestrator.generate_notes)

    tasks = [
        run_server(port=8765),
        run_caption_adapter(),
        _state_loop(orchestrator),
    ]
    if os.getenv("ENABLE_SCREEN", "true").lower() == "true":
        tasks.append(run_screen_adapter())
    else:
        logger.info("Screen adapter disabled (ENABLE_SCREEN=false)")

    # Audio adapter — automatic BACKUP that transcribes only when Meet captions
    # are off (no names from voice). No-ops gracefully if no loopback device.
    if os.getenv("ENABLE_AUDIO", "true").lower() == "true":
        tasks.append(run_audio_adapter())
    else:
        logger.info("Audio adapter disabled (ENABLE_AUDIO=false)")

    logger.info("Meeting Copilot live — open http://localhost:8765")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
