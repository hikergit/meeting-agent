import json
import logging
from typing import List

from contracts.decision import DecisionEvent, DecisionPayload
from contracts.meeting_state import MeetingState
from planning.llm import complete

logger = logging.getLogger(__name__)

_SYSTEM = """You verify factual claims from meetings. Only flag if you have meaningful evidence the claim is wrong.

{"accurate": true|false|null, "finding": "one-sentence assessment", "caveat": "if uncertain"}"""


class Researcher:
    def __init__(self, state: MeetingState):
        self.state = state

    async def verify(self, claim: str, trigger_obs_id: str) -> List[DecisionEvent]:
        try:
            result = json.loads(await complete(
                f'Verify this meeting claim: "{claim}"\n\nOutput JSON.',
                _SYSTEM, tier="mid"
            ))
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
