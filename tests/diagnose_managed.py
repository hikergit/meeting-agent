"""
Diagnostic: dump what a single managed-agent invocation actually returns.

Goal: figure out (a) whether agent emits text we can stream, and (b) what files
land in the sandbox under /workspace/.

Run:
  python tests/diagnose_managed.py
"""
import asyncio
import io
import os
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()


async def main():
    key = os.environ["GEMINI_API_KEY"]
    from google import genai
    client = genai.Client(api_key=key)

    task = (
        "Read every file under /workspace/docs/. "
        "Compare the claim '30% QoQ growth' against what those docs say. "
        "Write your verdict as HTML to /workspace/output.html. "
        "Then print a 2-3 sentence plain-text summary as your final message."
    )

    print("─── 1. Non-stream invocation, dump steps ───")
    def _run():
        return client.interactions.create(
            agent="meeting-doc-checker",
            input=task,
            environment="remote",
        )
    interaction = await asyncio.to_thread(_run)

    print(f"interaction.id           = {getattr(interaction, 'id', None)}")
    print(f"interaction.environment_id = {getattr(interaction, 'environment_id', None)}")
    print(f"interaction.status         = {getattr(interaction, 'status', None)}")
    print(f"interaction.output_text    = {repr(getattr(interaction, 'output_text', None))[:300]}")

    steps = getattr(interaction, "steps", None) or []
    print(f"\n{len(steps)} step(s):")
    for i, s in enumerate(steps):
        stype = getattr(s, "type", "?")
        attrs = {k: v for k, v in (s.__dict__.items() if hasattr(s, "__dict__") else [])
                 if k not in ("content",)}
        content = getattr(s, "content", None)
        c_summary = None
        if content:
            try:
                c_summary = [(getattr(c, "type", "?"), (getattr(c, "text", "")[:100] if hasattr(c, "text") else "")) for c in content]
            except Exception:
                c_summary = str(content)[:200]
        print(f"  [{i:02d}] type={stype}  attrs={attrs}  content={c_summary}")

    print("\n─── 2. Tarball download — list everything under /workspace ───")
    env_id = getattr(interaction, "environment_id", None)
    if not env_id:
        print("no environment_id, skipping download")
        return

    import httpx
    url = f"https://generativelanguage.googleapis.com/v1beta/files/environment-{env_id}:download"
    def _download():
        r = httpx.get(url, params={"alt": "media"},
                      headers={"x-goog-api-key": key},
                      follow_redirects=True, timeout=60.0)
        r.raise_for_status()
        return r.content

    tar_bytes = await asyncio.to_thread(_download)
    print(f"downloaded tar: {len(tar_bytes)} bytes")
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
        members = tar.getmembers()
        print(f"{len(members)} members:")
        for m in members:
            kind = "d" if m.isdir() else ("f" if m.isfile() else "?")
            if "workspace" in m.name or m.name.endswith(".html"):
                print(f"  {kind}  {m.size:8d}  {m.name}")

        # Try to read output.html (any path)
        for m in members:
            if m.name.endswith("output.html") and m.isfile():
                f = tar.extractfile(m)
                if f:
                    body = f.read().decode("utf-8", errors="replace")
                    print(f"\n─── output.html ({len(body)} chars) — first 500 chars ───")
                    print(body[:500])
                    break
        else:
            print("\n(no output.html in tar)")


if __name__ == "__main__":
    asyncio.run(main())
