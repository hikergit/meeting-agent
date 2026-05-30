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
from planning.dispatcher import Dispatcher
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
        self.dispatcher = Dispatcher(self.state)

        # Guardrails so the executor can't firehose Claude Code:
        #  - cap concurrent dispatches
        #  - skip tasks too similar to ones already running/done
        self._exec_sem = asyncio.Semaphore(int(os.getenv("EXECUTOR_MAX_CONCURRENT", "1")))
        self._dispatched: list[str] = []
        self._active_tasks = 0

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
        thinker_d, questioner_d, action_task, _ = await asyncio.gather(
            self.thinker.triage(obs),
            self.questioner.process(obs),
            self.dispatcher.detect(obs) if not MOCK else _none(),
            self.learner.process(obs),
        )

        for decision in [*thinker_d, *questioner_d]:
            await self._emit(decision)

        # 3. If an actionable request was heard, dispatch to Claude Code in background
        if action_task and self._should_dispatch(action_task):
            self._dispatched.append(action_task)
            notice = Dispatcher.working_notice(action_task, obs.id)
            await self._emit(notice)
            asyncio.create_task(self._run_executor(action_task, obs.id))

    def _should_dispatch(self, task: str) -> bool:
        """Skip if a very similar task was already dispatched (token-overlap > 0.6)."""
        words = set(task.lower().split())
        for prev in self._dispatched:
            pw = set(prev.lower().split())
            overlap = len(words & pw) / max(len(words | pw), 1)
            if overlap > 0.6:
                logger.info("⏭  Skipping duplicate task: %s", task[:50])
                return False
        return True

    async def _run_executor(self, task: str, obs_id: str) -> None:
        # Semaphore caps how many Claude Code dispatches run at once.
        async with self._exec_sem:
            self._active_tasks += 1
            try:
                for decision in await self.executor.run(task, obs_id):
                    await self._emit(decision)
            finally:
                self._active_tasks -= 1

    async def _emit(self, decision: DecisionEvent) -> None:
        from bus import bus
        await bus.publish("decision", decision)
        logger.info(
            "▶ Decision [%s] %.0f%% — %s",
            decision.urgency, decision.confidence * 100, decision.payload.title,
        )


async def _none():
    return None
