# 🛰️ Meeting Copilot

### A meeting agent built like a self-driving stack — **Perception → Planning → Action**

> It watches your meeting the way a self-driving car watches the road: a perception
> layer turns screen + speech into events, a Gemini planning brain reasons against
> *your own* work context, and an action layer quietly helps — catching contradictions,
> asking you the one question that matters, doing real work, and writing the notes.

*Built for the Google DeepMind **Enterprise Build Day** — agentic · multimodal · enterprise.*

---

## Why it matters

Meetings are lossy. People state numbers that contradict the plan, decisions evaporate,
action items never happen, and nobody can reconstruct what was actually said. Today's
"AI notetakers" transcribe and summarize *after the fact* — they don't **reason during
the meeting** or **act**.

Meeting Copilot does both, **privately, in real time**:

| The agent… | What that looks like |
|---|---|
| 👁️ **Sees & hears** | Reads Google Meet captions *and* screenshots the shared screen — so it understands the slide someone is presenting, not just the words. |
| 🧠 **Catches contradictions** | Cross-references on-screen claims against *your* mounted docs ("slide says 30% growth; your plan says 12%"). |
| ✋ **Asks when it needs you** | Surfaces *one* highlighted question when a decision genuinely unblocks it — not a wall of noise. |
| 🚀 **Does real work** | Hears "research X and build a dashboard" → dispatches an agent that searches the web and returns an embedded dashboard, live. |
| 📝 **Writes the notes** | Three tiers on demand: full transcript · detailed notes · a glanceable human recap. |

Everything surfaces in a **private side panel** — nothing is ever posted into the meeting.

---

## The demo (≈2 minutes)

1. **Join a real Google Meet, captions on.** The panel's *Conversation* fills with what the agent heard.
2. **Someone shares a slide.** The agent describes it (vision) and flags anything that contradicts your mounted docs.
3. **It asks you something** — a highlighted "needs you" question appears; you type back and it responds like a colleague.
4. **Say "research the latest X and build a dashboard."** The *Tasks & Results* panel shows live progress, then embeds the finished dashboard — no new tab.
5. **Hit 📝 Notes.** Out comes a five-bullet human recap, with links down to the detailed notes and full transcript.

---

## Why the architecture is the point

```
  ┌─────────────┐   observation    ┌────────────┐   decision    ┌──────────┐
  │ PERCEPTION  │ ───────────────▶ │  PLANNING  │ ────────────▶ │  ACTION  │
  │  adapters   │   (Contract A)   │  (Gemini)  │  (Contract B) │ adapters │
  └─────────────┘                  └────────────┘               └──────────┘
        captions / screen / audio    multi-agent brain          private panel
```

Every layer talks through **two fixed schemas** (`contracts/`). That's the enterprise story:
the perception adapters, the reasoning agents, and the action channels are all
**interchangeable** behind those contracts. Scaling from "one meeting on a laptop" to
"per-participant agents on the Meet Media API" is **adding adapters, not rewriting the core.**

**Multimodal** — vision (screen share) + transcript fused into one reasoning context.
**Agentic** — a multi-agent planning layer (Thinker, Questioner, Dispatcher, Researcher, Learner) that *decides whether to act*.
**Enterprise** — private by default, grounded in your own documents, produces real artifacts.

### Pluggable execution — local **or** cloud, one env var
The agent that does dispatched work is swappable:

```bash
EXECUTOR_BACKEND=claude    # local Claude Code subprocess (default)
EXECUTOR_BACKEND=managed   # Gemini Managed Agents — remote Linux sandboxes, web search
```

Same interface, same panel UX — proof the contract design holds.

---

## Quick start

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add GEMINI_API_KEY
python replay.py              # → open http://localhost:8765
```

No key handy? `MOCK_PLANNING=true python replay.py` runs the whole pipeline with rule-based stand-ins.

### Live mode
```bash
# Chrome with remote debugging (lets the agent read captions + screen via CDP)
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "--remote-debugging-port=9222" "--remote-allow-origins=http://localhost:9222"

python main.py                # join the meeting, turn captions ON, open localhost:8765
```

To enable contradiction-checking, drop your own `.md` docs in `planning/agent_config/sample_docs/`.

---

## Under the hood

| Layer | Pieces |
|------|--------|
| `contracts/` | Two schemas that are the *entire* integration surface — ObservationEvent, DecisionEvent |
| `perception/` | **caption** (Meet captions via Chrome DevTools) · **screen** (screenshots the Meet tab incl. shared screens → Gemini vision) · **audio** (STT backup when captions are off) |
| `planning/` | **Thinker** (contradictions) · **Questioner** (asks you) · **Dispatcher** (detects + routes work) · **Researcher** · **Learner** (facts) · **Notes** (3-tier) · **Conversation** (talks back) |
| `action/` | One private panel: live conversation · Tasks & Results · meeting notes |

**Models:** Gemini 3.x (3.1 Pro for deep reasoning, 3.5 Flash for fast paths + vision). Planning backend is swappable (Gemini / Claude / local / mock).

---

*Scoped for a 7-hour build: one perception path, a real multi-agent planning brain, one private action channel — chosen so the big version is adapters, not a rewrite.*
