"""
Learner — extracts and stores concrete facts asserted during the meeting.
Rate-limited to every 3rd transcript to reduce API spend.
"""
import asyncio
import json
import logging
import os
from typing import List

import google.generativeai as genai

from contracts.meeting_state import FactAsserted, MeetingState
from contracts.observation import ObservationEvent

logger = logging.getLogger(__name__)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

_SYSTEM = """You extract concrete, verifiable facts from meeting transcript lines.
A fact is a specific number, commitment, deadline, or decision — not an opinion or question.

Output JSON:
{"is_fact": true, "fact": "exact claim as stated"} or {"is_fact": false}"""


class Learner:
    def __init__(self, state: MeetingState):
        self.state = state
        self._model = genai.GenerativeModel(GEMINI_MODEL, system_instruction=_SYSTEM)
        self._n = 0

    async def process(self, obs: ObservationEvent) -> None:
        if obs.type != "transcript" or not obs.content.strip():
            return

        self._n += 1
        if self._n % 3 != 0:
            return

        speaker = obs.speaker.name if obs.speaker else "unknown"
        try:
            resp = await asyncio.to_thread(
                self._model.generate_content,
                f'Speaker: {speaker}\nSaid: "{obs.content}"\n\nOutput JSON.',
                generation_config=genai.GenerationConfig(response_mime_type="application/json"),
            )
            result = json.loads(resp.text)
            if result.get("is_fact") and result.get("fact"):
                self.state.facts_asserted.append(
                    FactAsserted(claim=result["fact"], by=speaker, at=obs.timestamp)
                )
                logger.debug("Fact: [%s] %s", speaker, result["fact"])
        except Exception as e:
            logger.error("Learner error: %s", e)
