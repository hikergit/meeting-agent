import asyncio
import json
import logging
import os
from typing import List

from google import genai
from google.genai import types

from contracts.meeting_state import FactAsserted, MeetingState
from contracts.observation import ObservationEvent

logger = logging.getLogger(__name__)

MODEL = "gemini-2.0-flash"  # simple extraction, runs frequently

_SYSTEM = """Extract concrete verifiable facts from meeting transcript lines.
A fact = specific number, commitment, deadline, or decision. Not opinions or questions.

Output JSON:
{"is_fact": true, "fact": "exact claim as stated"} or {"is_fact": false}"""


class Learner:
    def __init__(self, state: MeetingState):
        self.state = state
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
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
                self._client.models.generate_content,
                model=MODEL,
                contents=f'Speaker: {speaker}\nSaid: "{obs.content}"\n\nOutput JSON.',
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    response_mime_type="application/json",
                ),
            )
            result = json.loads(resp.text)
            if result.get("is_fact") and result.get("fact"):
                self.state.facts_asserted.append(
                    FactAsserted(claim=result["fact"], by=speaker, at=obs.timestamp)
                )
        except Exception as e:
            logger.error("Learner error: %s", e)
