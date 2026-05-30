import asyncio
import json
import logging
import os
from typing import List

from google import genai
from google.genai import types

from contracts.decision import DecisionEvent, DecisionPayload
from contracts.meeting_state import MeetingState

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"  # good knowledge, faster than pro

_SYSTEM = """You verify factual claims from meetings. Only flag if you have meaningful evidence the claim is wrong.

Output JSON:
{"accurate": true|false|null, "finding": "one-sentence assessment", "caveat": "if uncertain"}"""


class Researcher:
    def __init__(self, state: MeetingState):
        self.state = state
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    async def verify(self, claim: str, trigger_obs_id: str) -> List[DecisionEvent]:
        try:
            resp = await asyncio.to_thread(
                self._client.models.generate_content,
                model=MODEL,
                contents=f'Verify this meeting claim: "{claim}"\n\nOutput JSON.',
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    response_mime_type="application/json",
                ),
            )
            result = json.loads(resp.text)
            if result.get("accurate") is True:
                return []
            return [DecisionEvent(
                trigger_observation_ids=[trigger_obs_id],
                urgency="medium",
                confidence=0.5,
                payload=DecisionPayload(title="Claim needs verification", body=result.get("finding", claim)),
            )]
        except Exception as e:
            logger.error("Researcher error: %s", e)
            return []

    async def process(self, obs) -> List[DecisionEvent]:
        return []
