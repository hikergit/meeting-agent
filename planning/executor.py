"""
Executor — dispatches actionable requests heard in the meeting to local Claude Code.

When someone says e.g. "research the latest bio AI models and build a dashboard",
the executor hands that task to `claude -p` running headless with web + file tools.
Claude Code does the real work (web search, writes an HTML dashboard) in a scoped
workspace, and the result is surfaced privately in the side panel.

Runs in the background so it never blocks live caption processing.
"""
import asyncio
import json
import logging
import os
from pathlib import Path

from contracts.decision import DecisionEvent, DecisionPayload
from contracts.meeting_state import MeetingState

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent
WORKSPACE = REPO / "workspace"
OUTPUTS = REPO / "action" / "static" / "outputs"
TIMEOUT = int(os.getenv("EXECUTOR_TIMEOUT", "300"))  # seconds

# Tools Claude Code may use for a dispatched task.
_ALLOWED_TOOLS = "WebSearch WebFetch Read Write Edit Bash Glob Grep"


class Executor:
    def __init__(self, state: MeetingState):
        self.state = state
        WORKSPACE.mkdir(exist_ok=True)
        OUTPUTS.mkdir(parents=True, exist_ok=True)

    async def run(self, task: str, trigger_obs_id: str) -> list[DecisionEvent]:
        """Dispatch a task to local Claude Code. Returns the result decision(s)."""
        slug = "".join(c if c.isalnum() else "-" for c in task.lower())[:40].strip("-")
        out_name = f"{slug or 'task'}.html"
        prompt = (
            f"You are a meeting assistant acting on a live request: \"{task}\".\n\n"
            f"Do the real work now. If it requires research, use WebSearch/WebFetch. "
            f"Produce a self-contained HTML dashboard summarizing your findings and write it to "
            f"'{OUTPUTS / out_name}'. Use clean inline CSS, headings, and a comparison table where relevant.\n\n"
            f"After writing the file, print a 2-3 sentence plain-text summary of what you found. "
            f"Do not ask questions — make reasonable choices and finish."
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", prompt,
                "--allowedTools", *_ALLOWED_TOOLS.split(),
                "--permission-mode", "bypassPermissions",
                "--add-dir", str(OUTPUTS),
                cwd=str(WORKSPACE),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
            summary = (stdout.decode().strip() or stderr.decode().strip())[:600]

            produced = (OUTPUTS / out_name).exists()
            body = summary or "Task completed."
            if produced:
                body += f"\n\n📊 Dashboard: http://localhost:8765/static/outputs/{out_name}"

            return [DecisionEvent(
                trigger_observation_ids=[trigger_obs_id],
                action_type="surface_private",
                urgency="medium",
                confidence=0.9,
                payload=DecisionPayload(
                    title=f"✅ Done: {task[:50]}",
                    body=body,
                ),
            )]
        except asyncio.TimeoutError:
            return [DecisionEvent(
                trigger_observation_ids=[trigger_obs_id],
                urgency="low",
                confidence=0.5,
                payload=DecisionPayload(title="⏱ Task timed out", body=f"'{task}' exceeded {TIMEOUT}s"),
            )]
        except Exception as e:
            logger.error("Executor error: %s", e)
            return []
