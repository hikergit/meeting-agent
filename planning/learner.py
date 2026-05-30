import json
import logging

from contracts.meeting_state import FactAsserted, MeetingState
from contracts.observation import ObservationEvent
from planning.llm import complete

logger = logging.getLogger(__name__)

_SYSTEM = """Extract concrete verifiable facts from meeting transcript lines.
A fact = specific number, commitment, deadline, or decision. Not opinions or questions.

{"is_fact": true, "fact": "exact claim as stated"} or {"is_fact": false}"""


class Learner:
    def __init__(self, state: MeetingState):
        self.state = state
        self._n = 0

    async def process(self, obs: ObservationEvent) -> None:
        if obs.type != "transcript" or not obs.content.strip():
            return
        self._n += 1
        if self._n % 3 != 0:
            return
        speaker = obs.speaker.name if obs.speaker else "unknown"
        try:
            result = json.loads(await complete(
                f'Speaker: {speaker}\nSaid: "{obs.content}"\n\nOutput JSON.',
                _SYSTEM, tier="fast"
            ))
            if result.get("is_fact") and result.get("fact"):
                self.state.facts_asserted.append(
                    FactAsserted(claim=result["fact"], by=speaker, at=obs.timestamp)
                )
        except Exception as e:
            logger.error("Learner error: %s", e)
