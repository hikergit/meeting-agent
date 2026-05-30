"""
Dispatcher — detects when a transcript line is an actionable request
("research X", "build a dashboard for Y", "look up Z", "draft an email ...").
If so, it hands the task to the Executor (local Claude Code).

Fires per transcript line, like the Questioner. Cheap model.
"""
import json
import logging
from typing import List, Optional

from contracts.decision import DecisionEvent, DecisionPayload
from contracts.meeting_state import MeetingState
from contracts.observation import ObservationEvent
from planning.llm import complete

logger = logging.getLogger(__name__)

_SYSTEM = """You detect actionable work requests in meeting speech.

An ACTION is a request to DO something concrete: research a topic, look something up online,
build/draft/generate an artifact, compute, summarize external info, create a dashboard.

NOT an action: opinions, status updates, greetings, questions to other people, vague musings.

If it's an actionable request, rewrite it as a clear standalone task.

{"is_action": true, "task": "clear imperative task, self-contained"} or {"is_action": false}"""


class Dispatcher:
    def __init__(self, state: MeetingState):
        self.state = state

    async def detect(self, obs: ObservationEvent) -> Optional[str]:
        if obs.type != "transcript" or len(obs.content.split()) < 4:
            return None
        try:
            result = json.loads(await complete(
                f'Meeting speech: "{obs.content}"\n\nOutput JSON.',
                _SYSTEM, tier="fast"
            ))
            if result.get("is_action") and result.get("task"):
                return result["task"]
        except Exception as e:
            logger.error("Dispatcher error: %s", e)
        return None

    @staticmethod
    def working_notice(task: str, trigger_obs_id: str) -> DecisionEvent:
        return DecisionEvent(
            trigger_observation_ids=[trigger_obs_id],
            action_type="surface_private",
            urgency="medium",
            confidence=0.8,
            payload=DecisionPayload(
                title=f"🔧 Working on: {task[:50]}",
                body="Dispatched to local Claude Code — researching and building output…",
            ),
        )
