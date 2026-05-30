"""
Transcriber — updates MeetingState from raw observations.
No LLM calls: fast, deterministic, runs on every event.
"""
import logging

from contracts.meeting_state import MeetingState, Participant
from contracts.observation import ObservationEvent

logger = logging.getLogger(__name__)


class Transcriber:
    def __init__(self, state: MeetingState):
        self.state = state

    async def process(self, obs: ObservationEvent) -> None:
        if obs.type == "transcript":
            self._upsert_participant(obs)
            self.state.add_transcript(obs.model_dump())

        elif obs.type == "screen":
            self.state.current_screen = obs.content

        elif obs.type == "roster":
            self._handle_roster(obs)

    def _upsert_participant(self, obs: ObservationEvent) -> None:
        if not obs.speaker or not obs.speaker.name:
            return
        for p in self.state.participants:
            if p.id == obs.speaker.id:
                return
        self.state.participants.append(
            Participant(id=obs.speaker.id, name=obs.speaker.name)
        )

    def _handle_roster(self, obs: ObservationEvent) -> None:
        pid = obs.raw.get("participant_id", obs.content)
        name = obs.raw.get("name", obs.content)
        present = obs.raw.get("event") != "leave"
        for p in self.state.participants:
            if p.id == pid:
                p.present = present
                return
        if present:
            self.state.participants.append(Participant(id=pid, name=name))
