# Meeting Copilot

AI agent that watches your meeting and privately surfaces contradictions, gaps, and questions.

**Stack:** Perception → Planning (Gemini) → Action

## Quick start

```bash
cp .env.example .env   # add GEMINI_API_KEY
pip install -r requirements.txt
python replay.py       # open http://localhost:8765
```

## Live mode

```bash
# Launch Chrome with debugging
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# Start the agent
python main.py
```
Turn captions ON in Meet. Open http://localhost:8765.

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
