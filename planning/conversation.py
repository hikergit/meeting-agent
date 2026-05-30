"""
Conversation — generates the agent's human-like reply when the user answers it.

The flow in the main panel:
    👂 Heard        — what the agent picked up
    🤖 Agent        — its reaction / what it wants to know
    🧑 You          — your typed answer
    🤖 Agent reply  — THIS module: a short, natural response to your answer
"""
import logging

from contracts.meeting_state import MeetingState
from planning.llm import complete

logger = logging.getLogger(__name__)

_SYSTEM = """You are a meeting copilot talking privately with your user, like a sharp colleague.

You previously raised a point or question. The user just replied. Respond naturally and briefly
(1-2 sentences). Acknowledge their answer, and either close the loop or ask one crisp follow-up.
Be warm but concise. No preamble, no JSON — just what you'd say out loud."""


class Conversation:
    def __init__(self, state: MeetingState):
        self.state = state

    async def reply(self, agent_said: str, user_said: str) -> str:
        context = ""
        if self.state.transcript_window:
            recent = self.state.transcript_window[-5:]
            context = "\n".join(
                f"{t.get('speaker', {}).get('name', '?') if t.get('speaker') else '?'}: {t.get('content','')}"
                for t in recent
            )
        prompt = (
            f"Recent meeting context:\n{context or '(none)'}\n\n"
            f"You (the agent) said: \"{agent_said}\"\n"
            f"User replied: \"{user_said}\"\n\n"
            f"Your natural response:"
        )
        try:
            text = await complete(prompt, _SYSTEM, tier="mid", json_mode=False)
            return text.strip().strip('"')
        except Exception as e:
            logger.error("Conversation error: %s", e)
            return "Got it — thanks."
