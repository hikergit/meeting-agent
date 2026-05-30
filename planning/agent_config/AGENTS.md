# Meeting Copilot — Agent Config

## Mounted context
All `.md` files in `sample_docs/` are loaded into the Thinker's context at startup.
These represent the user's private work context — the documents against which meeting
claims are cross-referenced. Mount only synthetic or public docs (pre-GA API warning).

## Subagent registry

| Agent | File | Role | Fires on |
|-------|------|------|----------|
| Transcriber | transcriber.py | Updates MeetingState (no LLM) | Every observation |
| Learner | learner.py | Extracts asserted facts | Every 3rd transcript |
| Thinker | thinker.py | Detects contradictions & gaps | Every observation |
| Questioner | questioner.py | Suggests clarifying questions | Transcript only |
| Researcher | researcher.py | Verifies factual claims | Called by Thinker/Orchestrator |
| Executor | executor.py | Runs code snippets | Called explicitly |

## Surfacing policy
- Thinker confidence threshold: 0.6 minimum before surfacing.
- Public action channels (post_chat, speak, share_screen) are disabled today.
- Only `surface_private` decisions reach the side panel.

## Adding a new subagent
1. Create `planning/<name>.py` with an async `process(obs)` method.
2. Register it in `orchestrator.py`.
3. Add a row to this table.
