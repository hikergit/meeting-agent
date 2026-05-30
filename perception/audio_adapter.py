"""
Audio adapter — BACKUP transcription from local audio when Meet captions are off.

Reconstructed after the original (agent-authored) file was lost. Design follows
DESIGN.md §8 ("names come from Meet, never from voice").

Pipeline:
    loopback device (BlackHole 2ch) → sounddevice (16 kHz mono int16 PCM)
        → buffer ~CHUNK_SECONDS → Gemini transcription
        → type:"transcript" observation (speaker.name = null)

Coordination: this adapter is a BACKUP. It transcribes only while the caption
adapter reports captions are NOT active (see perception/source_state.py), so the
two never double-transcribe. Captions stay primary because they carry names.

Why batch chunks (not the Live API): the regular generateContent path uses a
model we've confirmed works on this account (gemini-2.5-flash) and supports audio
input. ~CHUNK_SECONDS latency is fine for a backup. Live API streaming is a
future optimization once a working live-model string is confirmed.

Setup (macOS — system audio is sandboxed, needs a loopback driver):
    1. brew install blackhole-2ch
    2. Audio MIDI Setup → Multi-Output Device (BlackHole + your speakers) so you
       still HEAR the meeting while it's captured.
    3. Point system/Chrome output at that Multi-Output Device.
    4. export AUDIO_INPUT_DEVICE="BlackHole"   # substring match (optional)
"""
import asyncio
import io
import logging
import os
import wave

from bus import bus
from contracts.observation import ObservationEvent
from perception import source_state

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHUNK_SECONDS = float(os.getenv("AUDIO_CHUNK_SECONDS", "5"))
DEVICE_HINT = os.getenv("AUDIO_INPUT_DEVICE", "BlackHole")
TRANSCRIBE_MODEL = "gemini-2.5-flash"

# Below this RMS the chunk is treated as silence and skipped (no API call).
SILENCE_RMS = int(os.getenv("AUDIO_SILENCE_RMS", "120"))


def _find_device() -> int | None:
    import sounddevice as sd
    for idx, dev in enumerate(sd.query_devices()):
        if DEVICE_HINT.lower() in dev["name"].lower() and dev["max_input_channels"] > 0:
            logger.info("Audio adapter using input device: %s", dev["name"])
            return idx
    return None


def _rms(pcm: bytes) -> float:
    import audioop
    return audioop.rms(pcm, 2) if pcm else 0


def _pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


async def _transcribe(pcm: bytes) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    wav = _pcm_to_wav(pcm)

    def _call():
        resp = client.models.generate_content(
            model=TRANSCRIBE_MODEL,
            contents=[
                "Transcribe this meeting audio verbatim. Output only the spoken words, "
                "no commentary. If silent or unintelligible, output nothing.",
                types.Part.from_bytes(data=wav, mime_type="audio/wav"),
            ],
        )
        return (resp.text or "").strip()

    return await asyncio.to_thread(_call)


async def run_audio_adapter() -> None:
    try:
        import sounddevice as sd  # noqa: F401
    except Exception as e:
        logger.warning("Audio adapter: sounddevice unavailable (%s) — disabled", e)
        return

    device = _find_device()
    if device is None:
        logger.warning(
            "Audio adapter: no input device matching %r found. "
            "Install BlackHole and set AUDIO_INPUT_DEVICE. Backup disabled.",
            DEVICE_HINT,
        )
        return

    import sounddevice as sd
    frames_per_chunk = int(SAMPLE_RATE * CHUNK_SECONDS)
    logger.info("Audio adapter ready (backup; %.0fs chunks, model=%s)", CHUNK_SECONDS, TRANSCRIBE_MODEL)

    loop = asyncio.get_event_loop()
    q: asyncio.Queue[bytes] = asyncio.Queue()

    def _cb(indata, frames, time_info, status):
        if status:
            logger.debug("audio status: %s", status)
        loop.call_soon_threadsafe(q.put_nowait, bytes(indata))

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="int16",
        blocksize=frames_per_chunk, device=device, callback=_cb,
    ):
        while True:
            pcm = await q.get()

            # Backup only: stay silent while captions are doing the job.
            if source_state.captions_recently_active():
                continue
            # Don't transcribe the agent's own TTS (prevents self-feedback loop).
            if source_state.agent_recently_spoke():
                continue
            if _rms(pcm) < SILENCE_RMS:
                continue

            try:
                text = await _transcribe(pcm)
            except Exception as e:
                logger.error("Audio transcription error: %s", e)
                continue

            if text:
                obs = ObservationEvent(
                    type="transcript",
                    source="audio_adapter",
                    speaker=None,  # Gemini does not diarize — no names from voice
                    content=text,
                    raw={"backup": True},
                )
                await bus.publish("observation", obs)
                logger.info("🎙  (audio backup) %s", text[:70])
