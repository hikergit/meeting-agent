"""
Executor — runs Python code snippets from execute_code decisions in a subprocess.
Timeout: 10s. Output capped at 500 chars.

Future: integrate Gemini Managed Agents API to give the executor real tool access
(create tickets, write files, call APIs) during the meeting.
See DESIGN.md §3.3 and the Gemini Managed Agents API docs.
"""
import asyncio
import logging
from typing import List

from contracts.decision import DecisionEvent, DecisionPayload
from contracts.meeting_state import MeetingState

logger = logging.getLogger(__name__)


class Executor:
    def __init__(self, state: MeetingState):
        self.state = state

    async def run(self, code: str, trigger_obs_id: str) -> List[DecisionEvent]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            output = (stdout.decode().strip() or stderr.decode().strip())[:500]
            return [DecisionEvent(
                trigger_observation_ids=[trigger_obs_id],
                action_type="surface_private",
                urgency="low",
                confidence=1.0,
                payload=DecisionPayload(title="Code result", body=output, code=code),
            )]
        except asyncio.TimeoutError:
            return [DecisionEvent(
                trigger_observation_ids=[trigger_obs_id],
                payload=DecisionPayload(title="Code timeout", body="Execution exceeded 10s", code=code),
            )]
        except Exception as e:
            logger.error("Executor error: %s", e)
            return []

    async def process(self, obs) -> List[DecisionEvent]:
        return []
