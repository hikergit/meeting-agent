import asyncio
import json
import logging
import os
from pathlib import Path
from typing import List

from google import genai
from google.genai import types

from contracts.decision import DecisionEvent, DecisionPayload, Evidence
from contracts.meeting_state import MeetingState
from contracts.observation import ObservationEvent

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-pro"
DOCS_DIR = Path(__file__).parent / "agent_config" / "sample_docs"

_SYSTEM = """You are the Thinker — the quiet reasoning core of a meeting copilot.

You receive a new observation (screen description or transcript line), the live meeting state,
and the user's mounted work-context documents.

Surface ONLY when you detect:
  (a) A claim in the meeting contradicts a specific fact in a mounted doc.
  (b) An assertion is vague or suspiciously unsupported.
  (c) Something is directly relevant to an open decision in the user's mounted docs.

Output valid JSON only.

If surfacing:
{"should_surface": true, "title": "headline ≤ 8 words", "body": "1–3 sentence explanation", "evidence": [{"source": "filename.md", "ref": "exact short quote"}], "urgency": "low|medium|high", "confidence": 0.85}

If silent:
{"should_surface": false}

Rules:
- Be conservative. One false positive costs more than a miss.
- Never fabricate evidence — only cite text literally in the doc.
- Title ≤ 8 words. Body ≤ 3 sentences."""


def _load_docs() -> str:
    if not DOCS_DIR.exists():
        return "(no docs mounted)"
    parts = [f"=== {f.name} ===\n{f.read_text()}" for f in sorted(DOCS_DIR.glob("*.md"))]
    return "\n\n".join(parts) if parts else "(no docs mounted)"


class Thinker:
    def __init__(self, state: MeetingState):
        self.state = state
        self._docs = _load_docs()
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    async def triage(self, obs: ObservationEvent) -> List[DecisionEvent]:
        prompt = (
            f"MOUNTED DOCS:\n{self._docs}\n\n"
            f"MEETING STATE:\n{self.state.model_dump_json(indent=2)}\n\n"
            f"NEW OBSERVATION:\n{obs.model_dump_json(indent=2)}\n\nAssess and output JSON only."
        )
        try:
            resp = await asyncio.to_thread(
                self._client.models.generate_content,
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    response_mime_type="application/json",
                ),
            )
            result = json.loads(resp.text)
            if not result.get("should_surface"):
                return []
            return [DecisionEvent(
                trigger_observation_ids=[obs.id],
                action_type="surface_private",
                channel="private",
                urgency=result.get("urgency", "medium"),
                confidence=float(result.get("confidence", 0.7)),
                payload=DecisionPayload(
                    title=result["title"],
                    body=result["body"],
                    evidence=[Evidence(**e) for e in result.get("evidence", [])],
                ),
            )]
        except Exception as e:
            logger.error("Thinker error: %s", e)
            return []
