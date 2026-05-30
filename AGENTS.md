# CLAUDE.md

This is a hackathon project: **Meeting Copilot** — a meeting agent built on a Perception → Planning → Action stack using Gemini and vision.

**Source of truth:** `DESIGN.md`. Read it before writing any code.

## Scope discipline (7-hour build)

Build only what is in the **"Build today (MVP)"** list in `DESIGN.md §0`. If you find yourself building anything on the "Do NOT build today" list, stop.

## Principles

- **Concise by default.** Lead with the answer. Don't over-explain.
- **Never assume.** Verify before acting. If a fact is load-bearing (API shape, model string, permission requirement), look it up or flag it.
- **Cite sources.** Any specific claim — API behavior, a flag, a schema — must include where you got it.
- **Math:** use Python, don't predict.
- **Done means done.** Only say "done" when it works end-to-end. If it can't be done, say so immediately.
- **Scope creep is a bug.** The contracts in `DESIGN.md §2` are fixed. Don't extend them speculatively.
