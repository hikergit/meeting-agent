"""
Unified LLM backend — swap between Claude, Gemini, or Mock via PLANNING_BACKEND env var.

Auto-detection order (when PLANNING_BACKEND=auto):
  1. ANTHROPIC_API_KEY present → claude
  2. GEMINI_API_KEY present    → gemini
  3. Neither                   → raises (use MOCK_PLANNING=true instead)

Model tiers:
  "smart" — most capable (Thinker)
  "fast"  — cheapest/fastest (Learner, screen vision)
  "mid"   — balanced (Questioner, Researcher)
"""
import asyncio
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_BACKEND = os.getenv("PLANNING_BACKEND", "auto").lower()

# Model maps
_CLAUDE = {
    "smart": "claude-opus-4-8",
    "mid":   "claude-sonnet-4-6",
    "fast":  "claude-haiku-4-5-20251001",
}
_GEMINI = {
    "smart": "gemini-3.1-pro-preview",   # deepest reasoning (Thinker)
    "mid":   "gemini-3.5-flash",
    "fast":  "gemini-3.5-flash",
}


def resolved_backend() -> str:
    if _BACKEND != "auto":
        return _BACKEND
    if os.getenv("ANTHROPIC_API_KEY"):
        return "claude"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    # Fall back to claude CLI if available (no key needed)
    import shutil
    if shutil.which("claude"):
        return "claude-cli"
    raise RuntimeError("Set ANTHROPIC_API_KEY or GEMINI_API_KEY, or use MOCK_PLANNING=true")


async def complete(prompt: str, system: str, tier: str = "mid") -> str:
    """Returns raw text. Callers parse JSON themselves."""
    backend = resolved_backend()
    if backend == "claude":
        return await _claude(prompt, system, tier)
    elif backend == "claude-cli":
        return await _claude_cli(prompt, system)
    elif backend == "gemini":
        return await _gemini(prompt, system, tier)
    else:
        raise RuntimeError(f"Unknown backend: {backend}")


async def _claude(prompt: str, system: str, tier: str) -> str:
    import anthropic
    model = _CLAUDE[tier]
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    full_system = system + "\n\nIMPORTANT: Output only valid JSON. No markdown fences, no explanation."

    def _call():
        msg = client.messages.create(
            model=model,
            max_tokens=1024,
            system=full_system,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    text = await asyncio.to_thread(_call)
    # Strip any accidental ```json ... ``` wrapping
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return text


async def _claude_cli(prompt: str, system: str) -> str:
    full = f"{system}\n\nIMPORTANT: Output only valid JSON, no markdown.\n\n{prompt}"
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", full,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    text = stdout.decode().strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return text


async def _gemini(prompt: str, system: str, tier: str) -> str:
    from google import genai
    from google.genai import types
    model = _GEMINI[tier]
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def _call():
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
            ),
        )
        return resp.text

    return await asyncio.to_thread(_call)


def log_backend() -> None:
    try:
        b = resolved_backend()
        if b == "claude-cli":
            logger.info("LLM backend: claude-cli (local Claude Code, no API key needed)")
        else:
            tier_map = _CLAUDE if b == "claude" else _GEMINI
            logger.info("LLM backend: %s (smart=%s, mid=%s, fast=%s)",
                        b, tier_map["smart"], tier_map["mid"], tier_map["fast"])
    except RuntimeError as e:
        logger.warning("LLM backend: %s", e)
