"""
Questioner — generates the one best clarifying question for vague or incomplete claims.
"""
import asyncio
import json
import logging
import os
from typing import List

import google.generativeai as genai

from contracts.decision import DecisionEvent, DecisionPayload
from contracts.meeting_state import MeetingState
from contracts.observation import ObservationEvent

logger = logging.getLogger(__name__)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

_SYSTEM = """You are the Questioner — you surface the one best follow-up question a smart attendee would ask.

Given a transcript line and the current meeting state, fire ONLY if:
  - Someone made a specific claim that would benefit from a targeted follow-up.
  - The question is not already in open_questions and is not obvious.

Output JSON:
{"should_question": true, "question": "≤20-word specific neutral question", "reason": "one sentence"}
or
{"should_question": false}"""


class Questioner:
    def __init__(self, state: MeetingState):
        self.state = state
        self._model = genai.GenerativeModel(GEMINI_MODEL, system_instruction=_SYSTEM)

    async def process(self, obs: ObservationEvent) -> List[DecisionEvent]:
        if obs.type != "transcript":
            return []

        prompt = (
            f"MEETING STATE:\n{self.state.model_dump_json(indent=2)}\n\n"
            f"NEW TRANSCRIPT LINE:\n{obs.model_dump_json(indent=2)}\n\n"
            "Output JSON."
        )
        try:
            resp = await asyncio.to_thread(
                self._model.generate_content,
                prompt,
                generation_config=genai.GenerationConfig(response_mime_type="application/json"),
            )
            result = json.loads(resp.text)
            if not result.get("should_question"):
                return []

            q = result["question"]
            self.state.open_questions.append(q)
            return [DecisionEvent(
                trigger_observation_ids=[obs.id],
                urgency="low",
                confidence=0.6,
                payload=DecisionPayload(title="Suggested question", body=q),
            )]
        except Exception as e:
            logger.error("Questioner error: %s", e)
            return []
