# Meeting Copilot

AI agent that watches your meeting and privately surfaces contradictions, gaps, and questions.

**Stack:** Perception → Planning (Gemini) → Action

## Quick start

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add GEMINI_API_KEY (or ANTHROPIC_API_KEY)
python replay.py       # open http://localhost:8765
```

No API key? `MOCK_PLANNING=true python replay.py` runs the full pipeline with rule-based decisions.

## Live mode

```bash
source .venv/bin/activate

# Launch Chrome with debugging
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "--remote-debugging-port=9222" \
  "--remote-allow-origins=http://localhost:9222"

# Start the agent
python main.py
```
Turn captions ON in Meet. Open http://localhost:8765.

## Model backends

Set `PLANNING_BACKEND` in `.env`: `gemini` (default), `claude` (Anthropic key), `claude-cli` (local Claude Code, no key), or `MOCK_PLANNING=true`.

## Structure

| Path | What |
|------|------|
| `contracts/` | Shared event schemas (ObservationEvent, DecisionEvent) |
| `perception/` | Screen adapter (vision) + caption adapter (Chrome CDP) |
| `planning/` | 6 subagents: Transcriber, Thinker, Questioner, Learner, Researcher, Executor |
| `action/` | Private side panel UI |
| `replay.py` | Test without a live meeting |

## The demo

`sample_stream.json` has a slide claiming **30% QoQ growth**. Mounted doc says **12%**. The agent catches it.
