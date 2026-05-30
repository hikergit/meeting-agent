"""
Mock thinker — rule-based, zero API calls.
Used when MOCK_PLANNING=true or when no API key is available.
Detects numbers in claims and flags anything with % or $ as worth surfacing.
Good enough to prove the full pipeline works before you have a real key.
"""
import re
import logging
from typing import List

from contracts.decision import DecisionEvent, DecisionPayload
from contracts.meeting_state import MeetingState
from contracts.observation import ObservationEvent

logger = logging.getLogger(__name__)

_NUMBER_RE = re.compile(r'\b(\d+(?:\.\d+)?)\s*(%|M|B|K)\b')


class MockThinker:
    def __init__(self, state: MeetingState):
        self.state = state

    async def triage(self, obs: ObservationEvent) -> List[DecisionEvent]:
        if obs.type not in ("transcript", "screen"):
            return []

        matches = _NUMBER_RE.findall(obs.content)
        if not matches:
            return []

        nums = [f"{v}{u}" for v, u in matches]
        return [DecisionEvent(
            trigger_observation_ids=[obs.id],
            action_type="surface_private",
            urgency="low",
            confidence=0.5,
            payload=DecisionPayload(
                title=f"[MOCK] Claim with numbers: {', '.join(nums)}",
                body=f"Detected figures {', '.join(nums)} in: \"{obs.content[:120]}\"",
                evidence=[],
            ),
        )]


class MockLearner:
    def __init__(self, state): self.state = state
    async def process(self, obs) -> None: pass


class MockQuestioner:
    def __init__(self, state: MeetingState):
        self.state = state

    async def process(self, obs: ObservationEvent) -> List[DecisionEvent]:
        if obs.type != "transcript" or "?" in obs.content:
            return []
        if len(obs.content.split()) < 8:
            return []
        q = f"Can you elaborate on: \"{obs.content[:60]}...\"?"
        self.state.open_questions.append(q)
        return [DecisionEvent(
            trigger_observation_ids=[obs.id],
            urgency="low",
            confidence=0.4,
            payload=DecisionPayload(title="[MOCK] Suggested question", body=q),
        )]
