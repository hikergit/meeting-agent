"""
Orchestrator — wires all planning subagents together.
Sequence per observation:
  1. Transcriber (sync state update, no LLM)
  2. Learner + Thinker + Questioner + Dispatcher (concurrent LLM calls)
  3. Publish any decisions to the bus
  4. If the dispatcher detects an actionable request, spawn a background
     executor task (de-duped) whose progress shows in the Tasks panel.

Executor selection (EXECUTOR_BACKEND, decoupled from PLANNING_BACKEND):
  - "managed" → ManagedExecutor (Gemini Managed Agents, remote Linux sandboxes).
  - anything else → local Claude Code Executor (default, verified).
  - MOCK_PLANNING=true → no executor; dispatcher disabled.
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
# Executor backend is DECOUPLED from PLANNING_BACKEND so the verified local
# Claude Code path stays the default even when planning runs on Gemini.
#   "claude"  → local Claude Code subprocess (default, verified)
#   "managed" → Gemini Managed Agents (remote Linux sandboxes)
EXECUTOR_BACKEND = os.getenv("EXECUTOR_BACKEND", "claude").lower()


class Orchestrator:
    def __init__(self, managed_agent_ids: dict | None = None):
        self.state = MeetingState()
        self.transcriber = Transcriber(self.state)
        self.researcher = Researcher(self.state)
        self.learner = Learner(self.state)
        self.dispatcher = Dispatcher(self.state)

        # Executor backend selection (user-configurable, default = local Claude Code).
        if EXECUTOR_BACKEND == "managed" and managed_agent_ids:
            from planning.managed_executor import ManagedExecutor
            self.executor = ManagedExecutor(self.state, managed_agent_ids)
            logger.info("🌐 Executor: Gemini Managed Agents (remote sandboxes)")
        else:
            self.executor = Executor(self.state)
            logger.info("💻 Executor: local Claude Code subprocess")
        from planning.conversation import Conversation
        self.conversation = Conversation(self.state)
        from planning.notes import Notes
        self.notes = Notes(self.state)

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
        # 1. Update state immediately (no LLM, < 1ms)
        await self.transcriber.process(obs)

        # Surface exactly what the agent heard in the conversation panel.
        if obs.type == "transcript":
            from action.side_panel import broadcast_heard
            sp = obs.speaker.name if obs.speaker else None
            await broadcast_heard(sp, obs.content)

        # 2. Run LLM-backed agents concurrently
        thinker_d, questioner_d, action_req, _ = await asyncio.gather(
            self.thinker.triage(obs),
            self.questioner.process(obs),
            self.dispatcher.detect(obs) if not MOCK else _none(),
            self.learner.process(obs),
        )

        for decision in [*thinker_d, *questioner_d]:
            await self._emit(decision)

        # 3. If an actionable request was heard, dispatch to the executor in background.
        #    Goes to the dedicated Tasks panel (with progress), NOT the scrolling chat.
        if action_req and self._should_dispatch(action_req.task):
            self._dispatched.append(action_req.task)
            asyncio.create_task(self._run_executor(action_req, obs.id))

    async def handle_user_reply(self, agent_said: str, user_said: str) -> str:
        """User typed a reply in the panel → agent responds like a colleague."""
        return await self.conversation.reply(agent_said, user_said)

    async def generate_notes(self) -> dict:
        """Produce the three-tier meeting record (raw / detailed / human)."""
        return await self.notes.generate()

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

    async def _run_executor(self, req, obs_id: str) -> None:
        import re
        from action.side_panel import broadcast_task_started, broadcast_task_done
        task, task_type = req.task, req.task_type
        task_id = obs_id
        # Announce immediately so the Tasks panel shows progress right away.
        await broadcast_task_started(task_id, task)
        # Semaphore caps how many executor dispatches run at once.
        async with self._exec_sem:
            self._active_tasks += 1
            try:
                decisions = await self.executor.run(task, obs_id, task_type=task_type)
                # Pull the dashboard URL + summary out of the result for the Tasks panel.
                url, summary = None, ""
                for d in decisions:
                    body = d.payload.body or ""
                    m = re.search(r"/static/outputs/[^\s]+\.html", body)
                    if m:
                        url = m.group(0)
                    summary = re.sub(r"📊[^\n]*", "", body).strip() or summary
                await broadcast_task_done(task_id, task, url, summary)
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
