"""Builds the xAI Voice Agent API session.update event from the prompt and tool schemas."""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = ROOT / "prompts" / "system_prompt.md"
TOOLS_PATH = ROOT / "tools" / "tools.json"


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def load_tools() -> list[dict[str, Any]]:
    return json.loads(TOOLS_PATH.read_text(encoding="utf-8"))


def build_session_update(voice: str = "Ara") -> dict[str, Any]:
    return {
        "type": "session.update",
        "session": {
            "voice": voice,
            "instructions": load_prompt(),
            "turn_detection": {"type": "server_vad"},
            "tools": load_tools(),
        },
    }
