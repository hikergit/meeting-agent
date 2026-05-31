import json
import logging
from typing import List

from contracts.decision import DecisionEvent, DecisionPayload
from contracts.meeting_state import MeetingState
from contracts.observation import ObservationEvent
from planning.llm import complete

logger = logging.getLogger(__name__)

_SYSTEM = """You are the agent's voice to YOUR USER (a private meeting copilot).

Output a question ONLY when you genuinely need the USER to clarify or decide something so you
can be helpful — a real, direct question addressed TO THE USER. Examples of valid questions:
  - "Want me to draft a follow-up email about the budget overrun?"
  - "Should I flag the 30% vs 12% discrepancy to the presenter, or just note it?"
  - "Do you want the cloud-renewal deadline added to your action items?"

Do NOT produce:
  - Rhetorical or generic questions ("What are the next steps?").
  - Questions aimed at meeting participants rather than your user.
  - Anything you could just do or note yourself without the user's input.

Be very conservative — most lines need NO question. Stay silent unless a user decision genuinely unblocks you.

{"should_question": true, "question": "direct question to the user, ≤18 words, ends with ?"}
or {"should_question": false}"""


import os
import time

COOLDOWN = float(os.getenv("QUESTION_COOLDOWN", "30"))  # min seconds between questions


class Questioner:
    def __init__(self, state: MeetingState):
        self.state = state
        self._last_q = 0.0

    async def process(self, obs: ObservationEvent) -> List[DecisionEvent]:
        if obs.type != "transcript":
            return []
        # Throttle: don't pepper the user with questions.
        if time.time() - self._last_q < COOLDOWN:
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
            self._last_q = time.time()
            self.state.open_questions.append(q)
            return [DecisionEvent(
                trigger_observation_ids=[obs.id],
                urgency="medium",
                confidence=0.6,
                payload=DecisionPayload(title="Suggested question", body=q),
            )]
        except Exception as e:
            logger.error("Questioner error: %s", e)
            return []
