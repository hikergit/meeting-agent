"""
Central configuration loader.

Non-secret settings live in config.toml (the source of truth). This maps them onto
the environment-variable names the modules already read, so the rest of the code is
unchanged and a shell env var can still override any value for a one-off run.

Precedence:  shell env  >  config.toml  >  code default.

Call load_config() once at startup, right after load_dotenv() and BEFORE importing
modules that read these settings at import time.
"""
import os
import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"

# toml dotted-path  →  ENV_VAR consumed by the code.
_MAP = {
    "planning.backend":                    "PLANNING_BACKEND",
    "planning.mock":                       "MOCK_PLANNING",
    "planning.questioner.cooldown_seconds":"QUESTION_COOLDOWN",
    "planning.dispatcher.disable_doc_check":"DISABLE_DOC_CHECK",
    "executor.backend":                    "EXECUTOR_BACKEND",
    "executor.max_concurrent":             "EXECUTOR_MAX_CONCURRENT",
    "executor.timeout_seconds":            "EXECUTOR_TIMEOUT",
    "executor.managed_timeout_seconds":    "MANAGED_EXECUTOR_TIMEOUT",
    "perception.screen.enabled":           "ENABLE_SCREEN",
    "perception.screen.source":            "SCREEN_SOURCE",
    "perception.screen.interval_seconds":  "SCREEN_INTERVAL",
    "perception.caption.self_name":        "SELF_NAME",
    "perception.audio.enabled":            "ENABLE_AUDIO",
    "perception.audio.input_device":       "AUDIO_INPUT_DEVICE",
    "perception.audio.chunk_seconds":      "AUDIO_CHUNK_SECONDS",
    "action.voice":                        "ENABLE_VOICE",
    "action.voice_name":                   "VOICE_NAME",
}


def _dig(data: dict, dotted: str):
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _to_env(val) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)


def load_config(path: Path = CONFIG_PATH) -> None:
    if not path.exists():
        return
    with open(path, "rb") as f:
        data = tomllib.load(f)
    for dotted, env_name in _MAP.items():
        val = _dig(data, dotted)
        if val is not None:
            os.environ.setdefault(env_name, _to_env(val))  # shell env wins
