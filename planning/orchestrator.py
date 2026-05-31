"""
Orchestrator — wires all planning subagents together.
Sequence per observation:
  1. Transcriber (sync state update, no LLM)
  2. Learner + Thinker + Questioner + Dispatcher (concurrent LLM calls)
  3. Publish any decisions to the bus
  4. If dispatcher detects actionable: maybe-supersede an in-flight task,
     otherwise spawn a new background executor task.

Executor selection (PLANNING_BACKEND):
  - "gemini" → ManagedExecutor (Gemini Managed Agents, remote Linux sandboxes,
    truly parallel because each task forks its own sandbox).
  - anything else → local Claude Code Executor.
  - MOCK_PLANNING=true → no executor; dispatcher disabled.

Semantic dedup:
  When two transcript lines mean similar things ("research ramen" → "actually
  top ramen in Tokyo" → "make that Shibuya area"), we want the agent to do the
  LATEST intent only. A cheap LLM call decides if the new request is a
  refinement of an active in-flight one; if yes, the old task is marked
  superseded (its result is dropped when it returns) and the new request runs.
"""
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from contracts.decision import DecisionEvent, DecisionPayload
from contracts.meeting_state import MeetingState
from contracts.observation import ObservationEvent
from planning.dispatcher import ActionRequest, Dispatcher
from planning.executor import Executor
from planning.learner import Learner
from planning.llm import complete
from planning.questioner import Questioner
from planning.researcher import Researcher
from planning.thinker import Thinker
from planning.transcriber import Transcriber

logger = logging.getLogger(__name__)

MOCK = os.getenv("MOCK_PLANNING", "false").lower() == "true"
BACKEND = os.getenv("PLANNING_BACKEND", "auto").lower()
INFLIGHT_MAX = 5  # only consider the most recent N in-flight tasks for merge


@dataclass
class _Inflight:
    req: ActionRequest
    obs_id: str
    task: asyncio.Task
    superseded: bool = False


_MERGE_SYS = """You decide if a new meeting request is a refinement, clarification,
or near-duplicate of any active task.

Examples of refinement: "research ramen" → "actually top ramen in Tokyo" → "just Shibuya".
Examples of NOT refinement: "research ramen" vs. "draft an email to the team" (different intents).

Reply JSON: {"merge_with": <index or null>}  (null = new task, not a refinement)"""


class Orchestrator:
    def __init__(self, managed_agent_ids: Optional[dict] = None):
        self.state = MeetingState()
        self.transcriber = Transcriber(self.state)
        self.researcher = Researcher(self.state)
        self.learner = Learner(self.state)
        self.dispatcher = Dispatcher(self.state)
        self._inflight: list[_Inflight] = []

        # Executor selection
        if MOCK:
            self.executor = None
        elif BACKEND == "gemini" and managed_agent_ids:
            from planning.managed_executor import ManagedExecutor
            self.executor = ManagedExecutor(self.state, managed_agent_ids)
            logger.info("🌐 Executor: Gemini Managed Agents (remote sandboxes)")
        else:
            self.executor = Executor(self.state)
            logger.info("💻 Executor: local Claude Code subprocess")

        if MOCK:
            from planning.mock_thinker import MockLearner, MockQuestioner, MockThinker
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

        # 2. Run LLM-backed agents concurrently
        thinker_d, questioner_d, action_req, _ = await asyncio.gather(
            self.thinker.triage(obs),
            self.questioner.process(obs),
            self.dispatcher.detect(obs) if (not MOCK and self.executor) else _none(),
            self.learner.process(obs),
        )

        for decision in [*thinker_d, *questioner_d]:
            await self._emit(decision)

        # 3. If an actionable request was heard, maybe-supersede or spawn
        if action_req:
            merged = await self._maybe_supersede(action_req, obs.id)
            if not merged:
                await self._spawn(action_req, obs.id, refined=False)

    async def _maybe_supersede(self, new_req: ActionRequest, obs_id: str) -> bool:
        """If new_req refines an in-flight task, mark it superseded and replace.
        Returns True if it replaced; caller should not spawn another."""
        # Clean up done tasks
        self._inflight = [t for t in self._inflight if not t.task.done()]
        if not self._inflight:
            return False

        # Build candidate list (only those of the same task_type — refinement
        # almost never crosses types)
        same_type = [(i, t) for i, t in enumerate(self._inflight) if t.req.task_type == new_req.task_type]
        if not same_type:
            return False

        candidates = "\n".join(f"{i}: {t.req.task}" for i, t in same_type)
        prompt = (
            f"Active in-flight tasks (same type={new_req.task_type}):\n{candidates}\n\n"
            f"New request: {new_req.task}\n\nOutput JSON."
        )
        try:
            raw = await complete(prompt, _MERGE_SYS, tier="fast")
            result = json.loads(raw)
            idx = result.get("merge_with")
            if idx is None:
                return False
            idx = int(idx)
            # Find the matching inflight by original index
            old = next((t for i, t in same_type if i == idx), None)
            if not old:
                return False
        except Exception as e:
            logger.error("supersede check failed: %s", e)
            return False

        # Mark old superseded — its result will be dropped in _run_executor
        old.superseded = True
        logger.info("🔁 Refining '%s' → '%s'", old.req.task[:50], new_req.task[:50])
        await self._spawn(new_req, obs_id, refined=True)
        return True

    async def _spawn(self, req: ActionRequest, obs_id: str, refined: bool) -> None:
        notice = Dispatcher.working_notice(req, obs_id)
        if refined:
            notice.payload.title = notice.payload.title.replace("🔧 ", "🔁 Refined — ", 1)
        await self._emit(notice)

        # Create and register the in-flight task BEFORE awaiting anything so
        # subsequent observations can see and supersede it.
        inflight = _Inflight(req=req, obs_id=obs_id, task=None)  # task filled below
        async def runner():
            return await self._run_executor(inflight)
        task = asyncio.create_task(runner())
        inflight.task = task
        self._inflight.append(inflight)
        self._inflight = self._inflight[-INFLIGHT_MAX:]

    async def _run_executor(self, inflight: _Inflight) -> None:
        decisions = await self.executor.run(
            inflight.req.task, inflight.obs_id, task_type=inflight.req.task_type
        )
        if inflight.superseded:
            logger.info("⏭  dropping stale result for '%s' (superseded)", inflight.req.task[:50])
            return
        for d in decisions:
            await self._emit(d)

    async def _emit(self, decision: DecisionEvent) -> None:
        from bus import bus
        await bus.publish("decision", decision)
        logger.info(
            "▶ Decision [%s] %.0f%% — %s",
            decision.urgency, decision.confidence * 100, decision.payload.title,
        )


async def _none():
    return None
