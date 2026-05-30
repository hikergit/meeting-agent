# Meeting Copilot — Technical Design Doc

**Status:** Build spec for hackathon (Google DeepMind Enterprise Build Day, May 30, build window 1pm–8pm, demos 8pm) . https://app.agihouse.org/events/gemini-build-day
**Audience:** Implementing engineers + Claude Code agents
**Thesis:** A meeting agent built like a self-driving stack — **Perception → Planning → Action** — where every module is interchangeable behind two fixed contracts. The agent watches a meeting, reasons against the user's own work context, and privately surfaces gaps, contradictions, and questions.

---

## 0. Read this first (scope discipline)

This is a 7-hour build. The architecture below describes a large system; **today you build a thin vertical slice of it.** The slice is chosen so that scaling up later means *adding adapters, not rewriting the core*.

**Build today (MVP):**
- One-and-a-half perception adapters: screen-share snapshot → vision, and caption transcript with names.
- Real planning layer (this is what's judged): a Gemini agent reasoning over mounted sample docs.
- One action channel: private surface-to-user side panel.

**Do NOT build today** (these are the "future version" — describe them on a slide, don't code them):
- Live audio capture, Deepgram, speaker diarization.
- Meet Media API / WebRTC client.
- Public action channels (post to chat, speak up, agent screen-share).
- Per-participant agents.
- Persistent cross-meeting memory.

If you find yourself building anything on the "do not build" list before the MVP demo works end-to-end, stop.

---

## 1. Architecture

```
  ┌─────────────┐     observation      ┌────────────┐     decision      ┌──────────┐
  │ PERCEPTION  │  ───────────────────▶│  PLANNING  │ ─────────────────▶│  ACTION  │
  │  adapters   │      (Contract A)    │  (Gemini)  │    (Contract B)   │ adapters │
  └─────────────┘                      └────────────┘                   └──────────┘
        │                                    ▲
        │            ┌──────────────┐        │
        └───────────▶│ MEETING STATE│────────┘
                     │  (shared)    │
                     └──────────────┘
```

- **Perception** turns raw inputs (screen, captions, later: audio/video) into normalized **observation events**. Every adapter emits the *same shape*. Adapters are mutually interchangeable.
- **Meeting State** is a running, queryable snapshot (who's here, what's been said, what's on screen, open questions). Perception writes it; Planning reads it instead of re-deriving from raw events.
- **Planning** is the Gemini multi-agent brain. Reads the observation stream + meeting state + the user's mounted work context. Decides whether to act and emits **decision events**.
- **Action** consumes decisions and executes through interchangeable output channels. Today: one channel (private).

**The two contracts (Section 2) are the entire integration surface.** Agree on them first; everything else develops in parallel against them.

---

## 2. Contracts (define these before anything else)

### Contract A — Observation event (Perception → Planning / Meeting State)

```jsonc
{
  "id": "uuid",
  "timestamp": "2026-05-30T13:00:00.000-07:00", // ISO 8601
  "type": "transcript" | "screen" | "chat" | "roster",
  "source": "caption_adapter" | "screen_adapter" | "chat_adapter" | "roster_adapter",
  "speaker": { "id": "string", "name": "string | null" } | null, // name null = unknown/in-room
  "content": "string",   // transcript line, vision description of screen, chat text, etc.
  "raw": { }             // optional adapter-specific payload (e.g. image path, frame index)
}
```

Rules:
- A transcript line from captions → `type:"transcript"`, `speaker.name` = real name from Meet.
- A screen frame → `type:"screen"`, `content` = vision model's text description, `speaker:null`.
- Adapters never reason. They only normalize and emit.

### Contract B — Decision event (Planning → Action)

```jsonc
{
  "id": "uuid",
  "timestamp": "ISO 8601",
  "trigger_observation_ids": ["uuid", "..."],
  "action_type": "surface_private" | "post_chat" | "speak" | "share_screen" | "execute_code",
  "channel": "private",          // TODAY: always "private"
  "urgency": "low" | "medium" | "high",
  "confidence": 0.0,             // 0–1; gates public channels in future version
  "payload": {
    "title": "string",
    "body": "string",
    "evidence": [ { "source": "Q1_planning.md", "ref": "short quote or line" } ],
    "code": "string | null"      // for execute_code only
  }
}
```

Rules:
- Today, Planning only ever emits `action_type:"surface_private"`, `channel:"private"`. The other action types exist in the schema so the future version is a config change, not a rewrite.
- `confidence` + `urgency` are the fields that will later route between private and public channels. Populate them now even though only private fires.

### Meeting State (shared object, lives in Planning's context)

```jsonc
{
  "participants": [ { "id": "string", "name": "string", "present": true } ],
  "transcript_window": [ /* last N observation events */ ],
  "current_screen": "string (latest vision description)",
  "open_questions": [ "string" ],
  "facts_asserted": [ { "claim": "string", "by": "name", "at": "ISO 8601" } ]
}
```

With Gemini's long context window, keep this in the agent's context rather than building a separate store. Render it in the UI — a visible, evolving meeting state is a strong demo beat.

---

## 3. Module specs

### 3.1 Perception — Screen adapter (HIGHEST VALUE, build first)

- **Input:** the room laptop's display (whatever is rendered, including the Meet-shared screen). We photograph the *rendered result*, so it works identically for remote or in-room presenters and never touches the presenter's machine.
- **Mechanism:** `getDisplayMedia()` (browser) or native screen-grab → capture one frame ~every 1s → send to Gemini vision → emit `type:"screen"` observation with the description.
- **Why first:** no diarization, no latency pressure, ≤1 fps is fine, and it carries the most information (slides, numbers, diagrams).
- **Acceptance:** with a slide deck on screen, the adapter emits a stream of accurate `screen` observations describing each slide within ~2s of a slide change.
- **GOTCHA:** `getDisplayMedia()` triggers a permission prompt; on macOS you also need Screen Recording permission in System Settings or you get a black frame. **Grant this on the actual demo laptop before the demo.**

### 3.2 Perception — Caption/transcript adapter

- **Input:** Google Meet live captions, read via Chrome DevTools MCP (or a content script) from the page DOM. Meet labels each caption line with the speaker's real display name.
- **Output:** `type:"transcript"` observations with `speaker.name` set to the real name (free, no diarization).
- **Acceptance:** spoken lines from remote participants appear as transcript observations tagged with correct names within ~1–2s.
- **GOTCHAS:**
  - Captions are **off by default** — someone must turn them on. Bake "turn on captions" into the demo runbook.
  - DOM scraping is brittle to Meet's CSS class changes. Hardcode to *today's* DOM; do not over-engineer.
  - **This is the MVP's single point of failure.** See the stunt-double fallback in Section 6.

### 3.3 Planning — Gemini agent

- **Platform:** Gemini Managed Agents API (preview). Build a managed agent with the user's work context mounted (sample/synthetic docs — see warning below), invoked by ID.
- **Structure:**
  - **Triage agent:** watches observation stream + meeting state. Stays silent unless it detects (a) a contradiction between a screen/transcript claim and a mounted doc, (b) an unclear or unsupported assertion, or (c) something relevant to the user's mounted work.
  - **Specialist subagents** dispatched on trigger: a *relevance checker* (cross-references mounted docs) and a *question generator*. A *researcher* (web) is optional/stretch.
- **Output:** `surface_private` decision events with `evidence` pointing at the specific doc that justified the flag.
- **Acceptance:** when a screen observation asserts a figure that conflicts with a mounted doc, Planning emits within a few seconds a `surface_private` decision whose `payload.body` names both numbers and whose `evidence` cites the doc.
- **⚠️ DATA WARNING:** The Managed Agents API is preview; Google says **do not use proprietary/confidential data** with pre-GA products. **Mount only synthetic or public sample docs. No NVIDIA-internal material.**
- **⚠️ AUTH:** Use a Gemini **API key**, not a personal subscription, for any headless/agent invocation.
- **MODEL STRING:** Confirm the exact current model string at the morning briefing (event headlines say "Gemini 3.5 Flash"; docs showed a `…-flash-live-preview` string for Live). Don't hardcode a guess.

### 3.4 Action — Private side panel (only channel today)

- **Input:** `surface_private` decision events.
- **Output:** render `payload.title` + `body` + `evidence` in a side panel / local web UI. Nothing is posted into the meeting.
- **Why private-only:** public actions (posting to chat, speaking up, grabbing screen-share) are socially aggressive and risky to demo live — a misfire happens *in the meeting*. Private is the better product default and the safer demo.
- **Acceptance:** decision events appear in the panel within ~1s, newest on top, each showing its evidence.

---

## 4. Repo structure

```
meeting-copilot/
  contracts/
    observation.ts        # Contract A type + validator
    decision.ts           # Contract B type + validator
    meeting_state.ts      # shared state type
  perception/
    screen_adapter.*      # getDisplayMedia → vision → observation
    caption_adapter.*     # Chrome DevTools MCP → observation
    sample_stream.json    # recorded observations for offline dev + demo fallback
  planning/
    agent_config/         # AGENTS.md, SKILL.md, mounted sample docs
    triage.*              # consumes observations, emits decisions
  action/
    side_panel/           # UI consuming decisions
  bus.*                   # in-process event bus (localhost WebSocket or simple emitter)
  RUNBOOK.md              # demo-day checklist (permissions, captions, model string)
```

---

## 5. Build plan & task split

Two engineers, splitting at the contracts. They do **not** block each other.

**First 20 minutes (together):** finalize `contracts/observation.ts` and `contracts/decision.ts`. Commit them. Record a `sample_stream.json` of ~20 observation events (a fake meeting with one planted contradiction) — this unblocks Planning immediately and doubles as the demo fallback.

**Engineer A — Perception + Action (the body):**
1. Event bus + contract validators.
2. Screen adapter (3.1) → real `screen` observations on the bus.
3. Side panel (3.4) consuming a *stubbed* decision emitter.
4. Caption adapter (3.2).
5. Wire real decisions from B into the panel at integration.
- *Works against:* a stubbed decision emitter until B is ready.

**Engineer B — Planning (the brain):**
1. Stand up the Gemini Managed Agent; mount sample docs.
2. Triage loop consuming `sample_stream.json` → emits `surface_private` decisions.
3. Relevance + question subagents.
4. Meeting-state object, rendered for the UI.
5. Swap `sample_stream.json` for A's live bus at integration.
- *Works against:* the recorded sample stream until A's live perception is ready.

**Integration:** the only join is the two schemas. When A emits real observations and consumes real decisions, and B reads the live bus instead of the file, you're done.

**Optional spike (one engineer, hard 60–90 min timebox, only if a Google mentor grants live access):** Meet Media API as a drop-in replacement for the caption adapter (named per-participant streams, no caption dependency). Behind Contract A, this is a one-adapter swap. If it doesn't land by ~2:30, kill it — you lose 90 min of one person, not the demo.

---

## 6. Fallbacks & demo safety

- **Stunt double for captions:** keep `sample_stream.json` wired so you can replay a recorded meeting through the *same* observation schema. If live captions misbehave on stage, replay the file — the demo is byte-identical downstream. Build this early, not at 7:45.
- **macOS screen-recording permission:** grant on the demo laptop in advance (Section 3.1 gotcha).
- **Captions on:** first line of the runbook.
- **Model string + API key:** confirmed and in env before 1:30, not at demo time.

---

## 7. The demo (the moment that sells it)

Plant a contradiction. Put a slide on screen claiming, say, "30% QoQ growth." Mount a sample `Q1_planning.md` that says 12%. Live, the agent quietly surfaces, in the private panel:

> **Possible contradiction — Slide 4**
> Slide claims 30% QoQ growth; your Q1 planning doc states 12%.
> *Evidence: Q1_planning.md*

That single beat — vision + cross-reference against the user's own context + judicious *private* surfacing — tells the whole story in ten seconds and maps directly onto the event's "agentic, multimodal, enterprise" framing.

**Narrative for the pitch:** "We built the perception→planning→action spine end-to-end with vision and one agent. Because the layers talk through two fixed contracts, scaling to per-participant agents and the Meet Media API is adding adapters, not rewriting." The scoped-down build becomes evidence the big version is real.

---

## 8. Technical reference (verify anything load-bearing at the briefing)

**Gemini Managed Agents API (preview)** — build a managed, sandboxed agent in one API call (Antigravity harness); it can plan, use skills, run code, search, and read/write files. Configure by mounting your own instructions + files (AGENTS.md / SKILL.md) and saving as an agent invoked by ID. *Do not use confidential data (pre-GA).*

**Gemini Live API** — stateful WebSocket; input audio = 16-bit PCM, 16kHz, little-endian; output 24kHz. Provides transcripts of input and output. Supports async/parallel function calls with response policies SILENT / WHEN_IDLE / INTERRUPT (this is the "listen quietly, only speak when useful" mechanism). **Does not do speaker diarization.** (Future audio path only.)

**Speaker diarization (future, NOT today)** — Gemini diarizes only in the *batch* audio-understanding path, not live. For live, dedicated STT (Deepgram Nova-3 for far-field/multi-speaker rooms; AssemblyAI streaming, sub-300ms) gives inline "Speaker N" labels. Names still come from Meet, never from voice.

**Omni Flash** — video *generation* model (10s clips with audio); no GA developer API. Not relevant to perception despite being on the event headline list.

**Meet Media API (the "correct" future perception layer)** — real-time audio/video/screen-share + participant metadata via WebRTC. Solves names natively: each participant gets a constant CSRC on join. C++/TS reference clients handle the WebRTC internals (3 receive-only audio descriptions, DTLS rules). **Blockers for today:** Developer Preview gate (Cloud project + OAuth principal + *all participants* must be enrolled; approval ~"a couple of days"); restricted OAuth scopes; **must deploy (localhost fails CORS for the REST calls), no SDK, getStats() heartbeat ~every 10s, send video assignment once.** Preview application submitted separately; only a mentor-granted pre-enrolled project makes this viable same-day.

---

## 9. References (for independent verification)

- Gemini Live API — https://ai.google.dev/gemini-api/docs/live-api
- Gemini audio / diarization — https://ai.google.dev/gemini-api/docs/audio
- Meet Media API overview — https://developers.google.com/workspace/meet/media-api/guides/overview
- Meet Media API concepts (WebRTC reqs) — https://developers.google.com/workspace/meet/media-api/guides/concepts
- Meet Media API TS quickstart — https://developers.google.com/workspace/meet/media-api/guides/ts
- Meet Media API sample clients — https://github.com/googleworkspace/meet-media-api-samples
- "What is the Meet Media API" (gotchas) — https://www.recall.ai/blog/what-is-the-google-meet-media-api
- Workspace Developer Preview Program — https://developers.google.com/workspace/preview

*Managed Agents API and exact Gemini model strings launched after this doc's research window — confirm specifics in the live docs / morning briefing before relying on them.*
