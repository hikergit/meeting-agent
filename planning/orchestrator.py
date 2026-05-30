"""
Orchestrator — wires all planning subagents together.
Sequence per observation:
  1. Transcriber (sync state update, no LLM)
  2. Learner + Thinker + Questioner (concurrent LLM calls)
  3. Publish any decisions to the bus
"""
import asyncio
import logging
import os

from contracts.decision import DecisionEvent
from contracts.meeting_state import MeetingState
from contracts.observation import ObservationEvent
from planning.executor import Executor
from planning.learner import Learner
from planning.questioner import Questioner
from planning.researcher import Researcher
from planning.thinker import Thinker
from planning.transcriber import Transcriber

logger = logging.getLogger(__name__)

MOCK = os.getenv("MOCK_PLANNING", "false").lower() == "true"


class Orchestrator:
    def __init__(self):
        self.state = MeetingState()
        self.transcriber = Transcriber(self.state)
        self.researcher = Researcher(self.state)
        self.learner = Learner(self.state)
        self.executor = Executor(self.state)

        if MOCK:
            from planning.mock_thinker import MockThinker, MockQuestioner, MockLearner
            self.thinker = MockThinker(self.state)
            self.questioner = MockQuestioner(self.state)
            self.learner = MockLearner(self.state)
            logger.info("🟡 Mock planning mode — no API calls")
        else:
            self.thinker = Thinker(self.state)
            self.questioner = Questioner(self.state)

    async def handle_observation(self, obs: ObservationEvent) -> None:
        from bus import bus

        # 1. Update state immediately (no LLM, < 1ms)
        await self.transcriber.process(obs)

        # 2. Run LLM-backed agents concurrently
        thinker_d, questioner_d, _ = await asyncio.gather(
            self.thinker.triage(obs),
            self.questioner.process(obs),
            self.learner.process(obs),
        )

        for decision in [*thinker_d, *questioner_d]:
            await bus.publish("decision", decision)
            logger.info(
                "▶ Decision [%s] %.0f%% — %s",
                decision.urgency,
                decision.confidence * 100,
                decision.payload.title,
            )
