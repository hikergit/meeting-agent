"""
Voice — speaks the agent's reaction aloud when it needs the user's attention.
Uses macOS `say` (zero dependencies). Toggle with ENABLE_VOICE=false.

Non-blocking: each utterance runs as a detached subprocess so the meeting loop
never waits on speech. A short queue avoids overlapping voices.
"""
import asyncio
import logging
import os
import shutil

logger = logging.getLogger(__name__)

# Visual-only by default (avoids meeting echo). Set ENABLE_VOICE=true to speak aloud.
ENABLED = os.getenv("ENABLE_VOICE", "false").lower() == "true" and bool(shutil.which("say"))
VOICE = os.getenv("VOICE_NAME", "Samantha")

_lock = asyncio.Lock()


async def speak(text: str) -> None:
    if not ENABLED or not text.strip():
        return
    # Keep spoken text short and natural.
    spoken = text.strip()
    if len(spoken) > 220:
        spoken = spoken[:217] + "..."
    async with _lock:  # serialize so utterances don't overlap
        # Tell the audio backup to ignore its own voice (~14 chars/sec speech).
        from perception import source_state
        source_state.mark_agent_speaking(len(spoken) / 14.0)
        try:
            proc = await asyncio.create_subprocess_exec(
                "say", "-v", VOICE, spoken,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception as e:
            logger.debug("voice error: %s", e)
