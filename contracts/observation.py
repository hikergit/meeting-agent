from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class Speaker(BaseModel):
    id: str
    name: Optional[str] = None


class ObservationEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    type: Literal["transcript", "screen", "chat", "roster"]
    source: Literal["caption_adapter", "screen_adapter", "chat_adapter", "roster_adapter"]
    speaker: Optional[Speaker] = None
    content: str
    raw: dict = Field(default_factory=dict)
