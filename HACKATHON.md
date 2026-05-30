# Hackathon Info

**Event:** Google DeepMind Enterprise Build Day
**Date:** May 30, 2026 · Build 1pm–8pm · Demo 8pm

## Deadlines

| Time | What |
|------|------|
| 1:00pm | Build starts |
| **7:00pm** | **Code submission deadline** |
| 7:30pm | Prep / practice demo |
| 8:00pm | Demos |

## API Keys & Credits

- Find Gemini staff at the event — they hand out API keys + credits on the spot
- Ask early, don't wait until 6pm
- Key goes in `.env` as `GEMINI_API_KEY`
- Confirm the exact model string with them too (`GEMINI_MODEL` in `.env`)

## Submission checklist

- [ ] Code pushed to GitHub before 7pm
- [ ] `replay.py` demo works end-to-end
- [ ] Side panel loads at http://localhost:8765
- [ ] Contradiction beat fires (30% vs 12% QoQ)
- [ ] RUNBOOK.md reviewed

## Demo pitch (30 sec)

> "We built a meeting agent on a Perception → Planning → Action spine. It watches your screen, reads captions, and quietly cross-references claims against your own docs. One agent, private surfacing, no meeting disruption. The layers talk through two fixed contracts — scaling to per-participant agents is adding adapters, not rewriting."
