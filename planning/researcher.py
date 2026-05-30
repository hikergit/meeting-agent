"""
Researcher — verifies specific factual claims using Gemini's knowledge.
Invoked explicitly by the Orchestrator when the Thinker flags a verifiable claim.
Future: swap to live web search (Gemini grounding tool or Tavily API).
"""
import asyncio
import json
import logging
import os
from typing import List

import google.generativeai as genai

from contracts.decision import DecisionEvent, DecisionPayload
from contracts.meeting_state import MeetingState

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"  # good knowledge, faster than pro

_SYSTEM = """You are the Researcher — you verify factual claims made in meetings.

Given a claim, assess its accuracy based on your knowledge.
Only flag if you have meaningful evidence the claim is wrong or needs verification.

Output JSON:
{"accurate": true|false|null, "finding": "one-sentence assessment", "caveat": "if uncertain"}"""


class Researcher:
    def __init__(self, state: MeetingState):
        self.state = state
        self._model = genai.GenerativeModel(GEMINI_MODEL, system_instruction=_SYSTEM)

    async def verify(self, claim: str, trigger_obs_id: str) -> List[DecisionEvent]:
        try:
            resp = await asyncio.to_thread(
                self._model.generate_content,
                f'Verify this meeting claim: "{claim}"\n\nOutput JSON.',
                generation_config=genai.GenerationConfig(response_mime_type="application/json"),
            )
            result = json.loads(resp.text)
            if result.get("accurate") is True:
                return []
            return [DecisionEvent(
                trigger_observation_ids=[trigger_obs_id],
                urgency="medium",
                confidence=0.5,
                payload=DecisionPayload(
                    title="Claim needs verification",
                    body=result.get("finding", claim),
                ),
            )]
        except Exception as e:
            logger.error("Researcher error: %s", e)
            return []

    async def process(self, obs) -> List[DecisionEvent]:
        # Called explicitly by Orchestrator, not on every event
        return []
