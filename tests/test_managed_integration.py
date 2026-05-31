"""
End-to-end verification for the Gemini Managed Agents integration.

Runs four levels of checks, each independent. Each prints clear ✅/❌.
Use to convince yourself the wiring works before demo day.

Requires:
  GEMINI_API_KEY in env (or .env loaded)

Usage:
  python tests/test_managed_integration.py             # all levels
  python tests/test_managed_integration.py --level 1   # just classification
  python tests/test_managed_integration.py --level 2   # + agent bootstrap
  python tests/test_managed_integration.py --level 3   # + one live invocation
  python tests/test_managed_integration.py --level 4   # + replay sim w/ actionable line
"""
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Allow `python tests/test_managed_integration.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger("test")


def need_key():
    if not os.environ.get("GEMINI_API_KEY"):
        print("❌ GEMINI_API_KEY not set. Add it to .env or export it.")
        sys.exit(1)


# ─── Level 1 ──────────────────────────────────────────────────────────────
# Dispatcher classification: does the LLM correctly tag actionable lines
# and skip non-actionable lines?
async def level_1_classification():
    print("\n=== Level 1: Dispatcher classification ===")
    need_key()
    os.environ["PLANNING_BACKEND"] = "gemini"
    from contracts.observation import ObservationEvent
    from contracts.meeting_state import MeetingState
    from planning.dispatcher import Dispatcher

    cases = [
        ("Good afternoon everyone.",                                   False, None),
        ("Hey can you research the latest bio AI models for me?",      True,  "research"),
        ("Please build a dashboard comparing our Q1 numbers to plan.", True,  "dashboard"),
        ("Is that consistent with what the Q1 planning doc says?",     True,  "doc_check"),
        ("Draft an email to the team about the timeline change.",      True,  "generic"),
        ("ARR is forty-eight million.",                                False, None),
    ]
    d = Dispatcher(MeetingState())
    passes = 0
    for content, expected_action, expected_type in cases:
        obs = ObservationEvent(type="transcript", source="caption_adapter",
                               speaker={"id":"u","name":"Test"}, content=content)
        req = await d.detect(obs)
        got_action = req is not None
        got_type = req.task_type if req else None
        ok = got_action == expected_action and (
            not expected_action or got_type == expected_type
        )
        mark = "✅" if ok else "❌"
        print(f"  {mark} {content[:55]:55s} → action={got_action}, type={got_type}")
        passes += ok
    print(f"  {passes}/{len(cases)} correct")
    return passes == len(cases)


# ─── Level 2 ──────────────────────────────────────────────────────────────
# Agent bootstrap: can we create the four specialists on Google's side?
async def level_2_bootstrap():
    print("\n=== Level 2: Agent bootstrap (client.agents.create) ===")
    need_key()
    from planning.managed_agents import ensure_specialists, task_types
    ids = await ensure_specialists()
    for tt in task_types():
        agent_id = ids.get(tt)
        mark = "✅" if agent_id else "❌"
        print(f"  {mark} {tt:12s} → {agent_id}")
    return all(ids.values())


# ─── Level 3 ──────────────────────────────────────────────────────────────
# Live invocation: actually call one specialist and inspect output.
async def level_3_live_invocation():
    print("\n=== Level 3: Live ManagedExecutor invocation ===")
    need_key()
    os.environ["PLANNING_BACKEND"] = "gemini"
    from contracts.meeting_state import MeetingState
    from planning.managed_agents import ensure_specialists
    from planning.managed_executor import ManagedExecutor

    ids = await ensure_specialists()
    me = ManagedExecutor(MeetingState(), ids)

    task = "Compare our Q1 revenue growth claim against the mounted docs and report the verdict in one paragraph."
    print(f"  → invoking meeting-doc-checker: {task[:60]}…")
    decisions = await me.run(task, "obs-test-1", task_type="doc_check")
    if not decisions:
        print("  ❌ no decision returned")
        return False
    d = decisions[0]
    print(f"  ✅ decision returned ({d.urgency}, conf={d.confidence})")
    print(f"     title: {d.payload.title}")
    print(f"     body:  {d.payload.body[:200]}…")
    out = Path(__file__).resolve().parent.parent / "action/static/outputs"
    files = list(out.glob("*.html"))
    if files:
        print(f"  ✅ HTML output saved: {files[-1].name}")
    else:
        print(f"  ⚠️  no HTML file in {out} (agent may have skipped writing)")
    return True


# ─── Level 4 ──────────────────────────────────────────────────────────────
# Full orchestrator path: inject a transcript line, watch the side panel.
async def level_4_orchestrator_path():
    print("\n=== Level 4: Full orchestrator path (no UI, in-process) ===")
    need_key()
    os.environ["PLANNING_BACKEND"] = "gemini"
    from contracts.observation import ObservationEvent
    from planning.managed_agents import ensure_specialists
    from planning.orchestrator import Orchestrator
    from bus import bus

    ids = await ensure_specialists()
    orch = Orchestrator(managed_agent_ids=ids)

    decisions = []
    async def collect(d):
        decisions.append(d)
        print(f"  📬 decision: [{d.urgency}] {d.payload.title}")
    bus.subscribe("decision", collect)

    obs = ObservationEvent(
        type="transcript", source="caption_adapter",
        speaker={"id":"u","name":"Verity"},
        content="Could you research what Gemini Managed Agents actually do and summarize?",
    )
    print(f"  ▶ injecting: {obs.content}")
    await orch.handle_observation(obs)

    # Background executor task — wait up to a few minutes
    print("  ⏳ waiting up to 5 min for executor to finish…")
    for _ in range(60):
        await asyncio.sleep(5)
        if any("✅" in d.payload.title for d in decisions):
            break
    done = [d for d in decisions if "✅" in d.payload.title]
    if done:
        print(f"  ✅ executor completed → {done[0].payload.title}")
        return True
    print("  ❌ executor did not finish within timeout")
    return False


LEVELS = {
    1: level_1_classification,
    2: level_2_bootstrap,
    3: level_3_live_invocation,
    4: level_4_orchestrator_path,
}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", type=int, choices=[1, 2, 3, 4], default=None,
                        help="Run only one level; default runs 1-4 sequentially")
    args = parser.parse_args()

    levels = [args.level] if args.level else [1, 2, 3, 4]
    results = {}
    for lvl in levels:
        try:
            results[lvl] = await LEVELS[lvl]()
        except Exception as e:
            print(f"  ❌ Level {lvl} raised: {type(e).__name__}: {e}")
            results[lvl] = False

    print("\n=== Summary ===")
    for lvl, ok in results.items():
        print(f"  Level {lvl}: {'✅ PASS' if ok else '❌ FAIL'}")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    asyncio.run(main())
