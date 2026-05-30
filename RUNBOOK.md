# Demo Day Runbook — Meeting Copilot

**Event:** Google DeepMind Enterprise Build Day · May 30, 2026 · Demo 8pm

---

## Pre-demo checklist (do before 7:45pm)

- [ ] `cp .env.example .env` and fill in `GEMINI_API_KEY`
- [ ] Confirm `GEMINI_MODEL` string with Google mentor (don't guess)
- [ ] macOS: grant **Screen Recording** permission to Terminal/iTerm
  - System Settings → Privacy & Security → Screen Recording
- [ ] macOS: grant **Screen Recording** to Chrome (same path)
- [ ] `pip install -r requirements.txt`
- [ ] `python replay.py` → open http://localhost:8765 → confirm side panel loads
- [ ] Confirm the contradiction fires: obs-006/007 (30% QoQ) should trigger a Thinker alert citing `Q1_planning.md` (12%)

---

## Running the demo

### Option A — Replay (no live meeting required, safe fallback)
```bash
python replay.py --interval 2
```
Open http://localhost:8765. Watch the contradiction surface at obs-006/007.

### Option B — Live meeting
1. Launch Chrome with remote debugging:
   ```bash
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
     --remote-debugging-port=9222 \
     --user-data-dir=/tmp/chrome-debug
   ```
2. Open meet.google.com, join the meeting.
3. **Turn captions ON** (CC button, bottom of Meet).
4. ```bash
   python main.py
   ```
5. Open http://localhost:8765.

---

## The demo beat (10 seconds)

Put a slide on screen that says **"30% QoQ growth"**.

The agent will quietly surface in the panel:

> **Possible contradiction — Revenue Growth**
> Slide claims 30% QoQ growth; your Q1 planning doc states 12%.
> *Evidence: Q1_planning.md — "Q1 actual QoQ growth: 12%"*

That's the whole story: vision → cross-reference → private surfacing.

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
