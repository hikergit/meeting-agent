"""
ManagedExecutor — dispatches in-meeting actionable requests to Gemini Managed Agents.

Parallel to planning.executor.Executor (which uses local Claude Code).
Same interface: `run(task, trigger_obs_id) -> list[DecisionEvent]`.

How it works:
  1. Caller passes task_type ("research" | "dashboard" | "doc_check" | "generic").
  2. We invoke the matching specialist via client.interactions.create(stream=True).
  3. Stream events back; collect final text + download /workspace/output.html.
  4. Save the HTML into action/static/outputs/ so the side panel can link to it.

Multiple tasks run truly in parallel because each invocation forks its own
remote Linux sandbox (per the Managed Agents docs).

Spec source: https://www.philschmid.de/gemini-managed-agents-developer-guide
SDK ref:     https://raw.githubusercontent.com/google-gemini/gemini-skills/refs/heads/main/skills/gemini-interactions-api/SKILL.md
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Optional

from contracts.decision import DecisionEvent, DecisionPayload
from contracts.meeting_state import MeetingState

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent
OUTPUTS = REPO / "action" / "static" / "outputs"
TIMEOUT = int(os.getenv("MANAGED_EXECUTOR_TIMEOUT", "600"))  # seconds, generous for sandbox


def _slug(task: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in task.lower())[:40].strip("-") or "task"


class ManagedExecutor:
    def __init__(self, state: MeetingState, agent_ids: Dict[str, str]):
        self.state = state
        self.agent_ids = agent_ids  # {task_type: agent_id} from ensure_specialists()
        OUTPUTS.mkdir(parents=True, exist_ok=True)

        from google import genai
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def _pick_agent(self, task_type: Optional[str]) -> str:
        return self.agent_ids.get(task_type or "generic") or self.agent_ids.get("generic")

    async def run(
        self,
        task: str,
        trigger_obs_id: str,
        task_type: Optional[str] = None,
    ) -> list[DecisionEvent]:
        agent_id = self._pick_agent(task_type)
        slug = _slug(task)
        out_name = f"{slug}.html"
        out_path = OUTPUTS / out_name

        input_text = (
            f"Live meeting request: \"{task}\"\n\n"
            f"Do the work now. Save your HTML deliverable to /workspace/output.html. "
            f"End with a 2-3 sentence plain-text summary."
        )

        try:
            interaction, summary = await asyncio.wait_for(
                self._invoke(agent_id, input_text),
                timeout=TIMEOUT,
            )
        except asyncio.TimeoutError:
            return [DecisionEvent(
                trigger_observation_ids=[trigger_obs_id],
                urgency="low",
                confidence=0.5,
                payload=DecisionPayload(
                    title="⏱ Managed agent timed out",
                    body=f"'{task}' exceeded {TIMEOUT}s in {agent_id}",
                ),
            )]
        except Exception as e:
            logger.error("ManagedExecutor error (%s): %s", agent_id, e)
            return [DecisionEvent(
                trigger_observation_ids=[trigger_obs_id],
                urgency="low",
                confidence=0.4,
                payload=DecisionPayload(
                    title="⚠️ Managed agent error",
                    body=f"{type(e).__name__}: {str(e)[:200]}",
                ),
            )]

        # Try to download /workspace/output.html → action/static/outputs/{slug}.html
        produced = await self._download_output(interaction, out_path)

        body = (summary or "Task completed.")[:600]
        if produced:
            body += f"\n\n📊 Output: http://localhost:8765/static/outputs/{out_name}"

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

    async def _invoke(self, agent_id: str, input_text: str) -> tuple[object, str]:
        """
        Non-streaming invocation. Returns (final_interaction, summary_text).

        We tried streaming first; verified empirically that the meeting use case
        only needs the final result, and the streaming path was hiding
        environment_id / output_text on some SDK versions. Non-stream is simpler
        and more reliable. Streamed progress UX would be nice future work.
        """
        def _run():
            return self._client.interactions.create(
                agent=agent_id,
                input=input_text,
                environment="remote",
            )

        interaction = await asyncio.to_thread(_run)
        summary = (getattr(interaction, "output_text", "") or "").strip()
        return interaction, summary

    async def _download_output(self, interaction, out_path: Path) -> bool:
        """
        Pull /workspace/output.html out of the sandbox into our static dir.
        Uses the environment files-download REST endpoint per the Schmid guide.
        Returns True if the file landed on disk.
        """
        if interaction is None:
            return False
        env_id = getattr(interaction, "environment_id", None)
        if not env_id:
            return False

        api_key = os.environ.get("GEMINI_API_KEY")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/files/"
            f"environment-{env_id}:download"
        )

        def _download():
            import io
            import tarfile
            import httpx
            r = httpx.get(
                url,
                params={"alt": "media"},
                headers={"x-goog-api-key": api_key},
                follow_redirects=True,
                timeout=60.0,
            )
            r.raise_for_status()
            tar_bytes = r.content
            # Tar typically has entries like "./workspace/output.html".
            # Match any path ending in output.html (agent might write elsewhere).
            with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
                # Prefer exact /workspace/output.html, fall back to any output.html
                exact, fallback = None, None
                for member in tar.getmembers():
                    if not member.isfile():
                        continue
                    if member.name.endswith("workspace/output.html"):
                        exact = member
                        break
                    if member.name.endswith("output.html"):
                        fallback = member
                chosen = exact or fallback
                if chosen:
                    f = tar.extractfile(chosen)
                    if f:
                        out_path.write_bytes(f.read())
                        logger.info("Downloaded %s (%d bytes) → %s",
                                    chosen.name, chosen.size, out_path)
                        return True
            return False

        try:
            return await asyncio.to_thread(_download)
        except Exception as e:
            logger.warning("Could not download sandbox output: %s", e)
            return False
