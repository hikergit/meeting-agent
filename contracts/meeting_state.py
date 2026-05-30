from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field

WINDOW_SIZE = 20


class Participant(BaseModel):
    id: str
    name: str
    present: bool = True


class FactAsserted(BaseModel):
    claim: str
    by: str
    at: str  # ISO 8601


class MeetingState(BaseModel):
    participants: List[Participant] = Field(default_factory=list)
    transcript_window: List[dict] = Field(default_factory=list)   # rolling, for LLM context
    full_transcript: List[dict] = Field(default_factory=list)     # complete, raw ground truth
    current_screen: str = ""
    screen_log: List[str] = Field(default_factory=list)           # every distinct screen seen
    open_questions: List[str] = Field(default_factory=list)
    facts_asserted: List[FactAsserted] = Field(default_factory=list)

    def add_transcript(self, obs_dict: dict) -> None:
        self.full_transcript.append(obs_dict)                     # never truncated
        self.transcript_window.append(obs_dict)
        if len(self.transcript_window) > WINDOW_SIZE:
            self.transcript_window = self.transcript_window[-WINDOW_SIZE:]
