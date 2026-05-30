"""
Notes — produces the three-tier meeting record at end (or on demand):

  1. RAW transcript      — complete ground truth, every line. No LLM.
  2. DETAILED note       — summary, what was discussed, decisions, action items,
                           open questions, flagged contradictions. (LLM)
  3. HUMAN note          — tiny, glanceable recap (≤5 bullets). People have a small
                           attention window; this is what they actually read, with a
                           link down to the detailed version. (LLM)

All three are written to action/static/outputs/ so the panel can show the human
version inline and link to the detailed + raw versions.
"""
import json
import logging
import time
from pathlib import Path

from contracts.meeting_state import MeetingState
from planning.llm import complete

logger = logging.getLogger(__name__)

OUTPUTS = Path(__file__).resolve().parent.parent / "action" / "static" / "outputs"

_DETAILED_SYSTEM = """You are a meeting scribe. From the transcript and extracted signals, write
DETAILED meeting notes in clean Markdown with these sections:

## Summary
2-4 sentences on what this meeting was about.

## Discussion
Bulleted, the main topics and what was said about each.

## Decisions & Facts
Concrete decisions, numbers, commitments.

## Action Items
- [ ] owner — task (if owner unclear, omit owner)

## Open Questions
Unresolved questions.

## Flags
Any contradictions or things to double-check.

Be accurate and grounded in the transcript. Omit empty sections."""

_HUMAN_SYSTEM = """You write the TINY human recap of a meeting — for someone with a small attention
window who just wants to remember what happened. Rules:
- At most 5 short bullets, each ≤ 12 words.
- One line at top: a 6-8 word headline.
- Only the things a person would actually want to recall. No filler.
- Plain Markdown. No preamble."""


def _transcript_text(state: MeetingState) -> str:
    lines = []
    for t in state.full_transcript:
        sp = (t.get("speaker") or {}).get("name") if t.get("speaker") else None
        lines.append(f"{sp or 'Unknown'}: {t.get('content','')}")
    return "\n".join(lines)


def _signals(state: MeetingState) -> str:
    facts = "\n".join(f"- {f.claim} ({f.by})" for f in state.facts_asserted)
    qs = "\n".join(f"- {q}" for q in state.open_questions)
    screens = "\n".join(f"- {s}" for s in state.screen_log)
    people = ", ".join(p.name for p in state.participants)
    return (
        f"Participants: {people or 'unknown'}\n\n"
        f"Facts asserted:\n{facts or '(none)'}\n\n"
        f"Open questions:\n{qs or '(none)'}\n\n"
        f"Screens/shared content:\n{screens or '(none)'}"
    )


class Notes:
    def __init__(self, state: MeetingState):
        self.state = state
        OUTPUTS.mkdir(parents=True, exist_ok=True)

    async def generate(self) -> dict:
        """Returns {human, detailed_url, raw_url, human_url}. Writes all three files."""
        ts = time.strftime("%Y%m%d-%H%M%S")
        transcript = _transcript_text(self.state)
        signals = _signals(self.state)

        # 1. RAW — no LLM
        raw_name = f"transcript_{ts}.md"
        (OUTPUTS / raw_name).write_text(f"# Full Transcript\n\n{transcript or '(empty)'}\n")

        # 2. DETAILED
        detailed_md = "(no content)"
        try:
            detailed_md = await complete(
                f"SIGNALS:\n{signals}\n\nTRANSCRIPT:\n{transcript or '(empty)'}\n\nWrite the detailed notes.",
                _DETAILED_SYSTEM, tier="smart", json_mode=False,
            )
        except Exception as e:
            logger.error("Detailed notes error: %s", e)
        detailed_name = f"notes_detailed_{ts}.md"
        (OUTPUTS / detailed_name).write_text(detailed_md)

        # 3. HUMAN
        human_md = "- (could not summarize)"
        try:
            human_md = await complete(
                f"SIGNALS:\n{signals}\n\nDETAILED NOTES:\n{detailed_md}\n\nWrite the tiny human recap.",
                _HUMAN_SYSTEM, tier="mid", json_mode=False,
            )
        except Exception as e:
            logger.error("Human notes error: %s", e)
        human_name = f"notes_human_{ts}.md"
        (OUTPUTS / human_name).write_text(human_md)

        logger.info("📝 Notes generated (raw/detailed/human) → %s", OUTPUTS)
        base = "/static/outputs"
        return {
            "human": human_md,
            "human_url": f"{base}/{human_name}",
            "detailed_url": f"{base}/{detailed_name}",
            "raw_url": f"{base}/{raw_name}",
        }
