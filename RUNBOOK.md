# Demo Day Runbook — Meeting Copilot

**Event:** Google DeepMind Enterprise Build Day · May 30, 2026 · Demo 8pm

---

## Pre-demo checklist (do before 7:45pm)

- [ ] `python3.11 -m venv .venv && source .venv/bin/activate`
- [ ] `pip install -r requirements.txt`
- [ ] `cp .env.example .env` and fill in `GEMINI_API_KEY`
- [ ] macOS: grant **Screen Recording** permission to Terminal/iTerm
  - System Settings → Privacy & Security → Screen Recording
- [ ] macOS: grant **Screen Recording** to Chrome (same path)
- [ ] `python replay.py` → open http://localhost:8765 → confirm side panel loads
- [ ] Join a meeting, turn captions ON, confirm the Conversation panel shows what's heard

---

## Running the demo

### Option A — Replay (no live meeting required, safe fallback)
```bash
python3.11 replay.py --interval 2
```
Open http://localhost:8765. Watch the contradiction surface at obs-006/007.

### Option B — Live meeting
1. Launch Chrome with remote debugging:
   ```bash
   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
     "--remote-debugging-port=9222" \
     "--remote-allow-origins=http://localhost:9222" \
     "--user-data-dir=/tmp/chrome-debug"
   ```
2. Open meet.google.com, join the meeting.
3. **Turn captions ON** (CC button, bottom of Meet).
4. ```bash
   python3.11 main.py
   ```
5. Open http://localhost:8765.

---

## The demo beats

1. **It listens** — speak in the meeting; the Conversation panel shows what it heard.
2. **It asks you** — when it needs a decision, a highlighted question appears ("needs you").
3. **It acts** — say "research X and build a dashboard"; the Tasks panel shows live
   progress, then embeds the result (no new tab).
4. **It wraps up** — hit 📝 Notes for the glanceable human recap, with links to the
   detailed notes and full transcript.

Optional cross-reference beat: drop a real doc in `planning/agent_config/sample_docs/`
and the agent will flag claims on screen that contradict it.

---

## Fallback order
1. `replay.py` — always works, requires only GEMINI_API_KEY
2. `main.py` with screen adapter only (caption_adapter off) — no Chrome needed
3. `main.py` full live — needs Chrome CDP + Meet captions on

---

## Subagent quick ref

| Agent | What it does |
|-------|-------------|
| Transcriber | Updates state from captions/screen (no LLM) |
| Thinker | Detects contradictions against mounted docs |
| Questioner | Suggests follow-up questions |
| Learner | Logs asserted facts |
| Researcher | Verifies claims (called by Thinker) |
| Executor | Runs Python snippets on demand |

---

## If something breaks

| Problem | Fix |
|---------|-----|
| `GEMINI_API_KEY not set` | `cp .env.example .env` and fill in key |
| Black screen in screen adapter | Grant Screen Recording permission to Terminal |
| No captions / caption adapter loops | Verify `--remote-debugging-port=9222`; check captions are ON in Meet |
| Side panel not loading | Check port 8765 is free: `lsof -i :8765` |
| Thinker not firing | Check model string in `.env`; try `replay.py` first |
