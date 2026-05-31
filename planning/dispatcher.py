"""
Dispatcher — detects when a transcript line is an actionable request
("research X", "build a dashboard for Y", "look up Z", "draft an email ...").
If so, it returns an ActionRequest (task + task_type) that the orchestrator
hands to whichever executor is wired up (local Claude Code or Gemini Managed Agent).

Fires per transcript line, like the Questioner. Cheap model.
"""
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from contracts.decision import DecisionEvent, DecisionPayload
from contracts.meeting_state import MeetingState
from contracts.observation import ObservationEvent
from planning.llm import complete

logger = logging.getLogger(__name__)

_VALID_TYPES = {"research", "dashboard", "doc_check", "generic"}
# Set DISABLE_DOC_CHECK=true for demos where mounted docs are unrelated to the topic
# (e.g. travel meeting with Q1 planning docs mounted) — doc_check falls back to generic.
_DISABLE_DOC_CHECK = os.getenv("DISABLE_DOC_CHECK", "false").lower() == "true"

_SYSTEM = """You detect actionable work requests in meeting speech.

An ACTION is a request to DO something concrete: research a topic, look something up online,
build/draft/generate an artifact, compute, summarize external info, create a dashboard,
cross-check a claim against the user's own documents.

NOT an action: opinions, status updates, greetings, questions to other people, vague musings.

If it's an actionable request, rewrite it as a clear standalone task AND classify it:
  - "research"    → information gathering / web search / "find out about X"
  - "dashboard"   → "build / make / visualize / draft a dashboard / chart / report"
  - "doc_check"   → "is that consistent with our docs / what does the planning doc say"
  - "generic"     → actionable but doesn't fit the above

{"is_action": true, "task": "clear imperative task, self-contained", "task_type": "research|dashboard|doc_check|generic"}
or {"is_action": false}"""


@dataclass
class ActionRequest:
    task: str
    task_type: str  # one of _VALID_TYPES


class Dispatcher:
    def __init__(self, state: MeetingState):
        self.state = state

    async def detect(self, obs: ObservationEvent) -> Optional[ActionRequest]:
        if obs.type != "transcript" or len(obs.content.split()) < 4:
            return None
        try:
            result = json.loads(await complete(
                f'Meeting speech: "{obs.content}"\n\nOutput JSON.',
                _SYSTEM, tier="fast"
            ))
            if not result.get("is_action") or not result.get("task"):
                return None
            ttype = result.get("task_type", "generic")
            if ttype not in _VALID_TYPES:
                ttype = "generic"
            if _DISABLE_DOC_CHECK and ttype == "doc_check":
                ttype = "generic"
            return ActionRequest(task=result["task"], task_type=ttype)
        except Exception as e:
            logger.error("Dispatcher error: %s", e)
        return None

    @staticmethod
    def working_notice(req: "ActionRequest", trigger_obs_id: str) -> DecisionEvent:
        label = {
            "research": "Researching",
            "dashboard": "Building dashboard",
            "doc_check": "Cross-checking docs",
            "generic": "Working on",
        }.get(req.task_type, "Working on")
        return DecisionEvent(
            trigger_observation_ids=[trigger_obs_id],
            action_type="surface_private",
            urgency="medium",
            confidence=0.8,
            payload=DecisionPayload(
                title=f"🔧 {label}: {req.task[:50]}",
                body=f"Dispatched to specialist agent ({req.task_type})…",
            ),
        )
