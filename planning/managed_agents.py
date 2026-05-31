"""
Managed agent bootstrap — pre-defines specialist Gemini Managed Agents.

Run once at startup (when PLANNING_BACKEND=gemini). Each specialist forks a
fresh Linux sandbox per invocation, with the user's mounted work-context docs
already in /workspace/docs.

Spec source: https://www.philschmid.de/gemini-managed-agents-developer-guide
SDK ref:     https://raw.githubusercontent.com/google-gemini/gemini-skills/refs/heads/main/skills/gemini-interactions-api/SKILL.md

Idempotent: tries client.agents.get(id) first; only creates if missing.
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).parent / "agent_config" / "sample_docs"
BASE_AGENT = "antigravity-preview-05-2026"  # source: SKILL.md "Current Agents"

# Specialist definitions. Each maps task_type → (agent_id, system_instruction).
# Output convention: every specialist writes /workspace/output.html and ends with
# a 2-3 sentence plain-text summary so ManagedExecutor can stream it back.
_SPECIALISTS = {
    "research": (
        "meeting-researcher",
        "You are a meeting research specialist. When invoked, the user is in a "
        "live meeting and just asked for research on a topic. Do the real work:\n"
        "1. Use Google Search to gather current, citable sources.\n"
        "2. Cross-reference 2-3 sources before stating a fact.\n"
        "3. Write a self-contained HTML briefing to /workspace/output.html "
        "with headings, key findings, and a sources section (links).\n"
        "4. End your final message with a 2-3 sentence plain-text summary.\n\n"
        "User context docs are mounted at /workspace/docs/. Reference them if relevant.\n"
        "Be decisive — do not ask clarifying questions."
    ),
    "dashboard": (
        "meeting-dashboard-builder",
        "You build self-contained HTML dashboards on demand for a meeting copilot.\n"
        "1. Gather any needed data (web search OK, or use /workspace/docs/).\n"
        "2. Produce one HTML file at /workspace/output.html with inline CSS, "
        "headings, comparison tables, and (if useful) inline SVG charts.\n"
        "3. Keep it single-file — no external scripts except Chart.js / Grid.js / Mermaid CDN.\n"
        "4. End with a 2-3 sentence plain-text summary of what the dashboard shows.\n\n"
        "Be decisive — do not ask clarifying questions."
    ),
    "doc_check": (
        "meeting-doc-checker",
        "You cross-reference a claim heard in a meeting against the user's mounted docs.\n"
        "Docs are at /workspace/docs/. For the given claim:\n"
        "1. Read every mounted doc.\n"
        "2. Find any contradictions or supporting evidence — quote exactly.\n"
        "3. Write findings to /workspace/output.html (table: claim | doc | quote | verdict).\n"
        "4. End with a 2-3 sentence plain-text verdict.\n\n"
        "Be conservative — only flag contradictions with direct quoted evidence."
    ),
    "generic": (
        "meeting-generic-helper",
        "You are a general meeting assistant. The user is in a live meeting and "
        "asked you to do something. Interpret reasonably and:\n"
        "1. Do the work (web, code, files — Linux sandbox is yours).\n"
        "2. Save any artifact to /workspace/output.html.\n"
        "3. End with a 2-3 sentence plain-text summary.\n\n"
        "Mounted docs: /workspace/docs/. Be decisive — no clarifying questions."
    ),
}


def _mount_docs() -> list[dict]:
    """Build inline sources mounting every .md in agent_config/sample_docs/."""
    if not DOCS_DIR.exists():
        return []
    sources = []
    for f in sorted(DOCS_DIR.glob("*.md")):
        sources.append({
            "type": "inline",
            "target": f"/workspace/docs/{f.name}",
            "content": f.read_text(),
        })
    return sources


async def _get_or_create(client, agent_id: str, system_instruction: str, sources: list[dict]) -> str:
    """Idempotent: return existing agent ID, or create it."""
    # Try fetch
    try:
        agent = await asyncio.to_thread(lambda: client.agents.get(id=agent_id))
        logger.info("  ✓ %s already exists", agent_id)
        return agent.id if hasattr(agent, "id") else agent_id
    except Exception as e:
        # 404 / NotFound → create. Other errors propagate.
        msg = str(e).lower()
        if "not found" not in msg and "404" not in msg and "does not exist" not in msg:
            logger.warning("  agents.get(%s) raised non-404: %s — attempting create anyway", agent_id, e)

    # Create
    def _create():
        return client.agents.create(
            id=agent_id,
            base_agent=BASE_AGENT,
            system_instruction=system_instruction,
            base_environment={
                "type": "remote",
                "sources": sources,
            },
        )
    agent = await asyncio.to_thread(_create)
    logger.info("  + created %s", agent_id)
    return agent.id if hasattr(agent, "id") else agent_id


async def ensure_specialists() -> Dict[str, str]:
    """
    Ensure all specialist agents exist on Google's side. Returns {task_type: agent_id}.
    Safe to call repeatedly. Raises if GEMINI_API_KEY missing.
    """
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY required for managed agents")

    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    sources = _mount_docs()
    logger.info("Bootstrapping %d managed agents (mounting %d docs)…",
                len(_SPECIALISTS), len(sources))

    mapping: Dict[str, str] = {}
    for task_type, (agent_id, instr) in _SPECIALISTS.items():
        try:
            mapping[task_type] = await _get_or_create(client, agent_id, instr, sources)
        except Exception as e:
            logger.error("  ✗ failed to ensure %s: %s", agent_id, e)
            # Fall back to base agent for this task_type so the executor still works
            mapping[task_type] = BASE_AGENT

    return mapping


def task_types() -> list[str]:
    return list(_SPECIALISTS.keys())
