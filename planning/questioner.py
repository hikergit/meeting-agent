import json
import logging
from typing import List

from contracts.decision import DecisionEvent, DecisionPayload
from contracts.meeting_state import MeetingState
from contracts.observation import ObservationEvent
from planning.llm import complete

logger = logging.getLogger(__name__)

_SYSTEM = """You are the Questioner. Surface the one best follow-up question a smart attendee would ask.

Fire ONLY if someone made a claim needing a targeted follow-up not already in open_questions.

{"should_question": true, "question": "≤20-word specific neutral question", "reason": "one sentence"}
or {"should_question": false}"""


class Questioner:
    def __init__(self, state: MeetingState):
        self.state = state

    async def process(self, obs: ObservationEvent) -> List[DecisionEvent]:
        if obs.type != "transcript":
            return []
        prompt = (
            f"MEETING STATE:\n{self.state.model_dump_json(indent=2)}\n\n"
            f"NEW TRANSCRIPT LINE:\n{obs.model_dump_json(indent=2)}\n\nOutput JSON."
        )
        try:
            result = json.loads(await complete(prompt, _SYSTEM, tier="mid"))
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
