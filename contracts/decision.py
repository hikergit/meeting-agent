from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    source: str
    ref: str


class DecisionPayload(BaseModel):
    title: str
    body: str
    evidence: List[Evidence] = Field(default_factory=list)
    code: Optional[str] = None


class DecisionEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trigger_observation_ids: List[str] = Field(default_factory=list)
    action_type: Literal[
        "surface_private", "post_chat", "speak", "share_screen", "execute_code"
    ] = "surface_private"
    channel: Literal["private"] = "private"
    urgency: Literal["low", "medium", "high"] = "medium"
    confidence: float = 0.0
    payload: DecisionPayload
