"""Opt-out local, plain-text transcript. No tool arguments, credentials, or audio recordings.

This is a local file containing personal conversations. Exclude it from exports.
"""
from __future__ import annotations
from datetime import datetime
import os
from pathlib import Path
import re
import threading
import time
from nexus import diagnostics as diag

# NEXUS_ACTIVITY_LOG=0 disables storing new turns (existing file is untouched).
PATH = diag.LOGS / "Activity.log"
_LOCK = threading.RLock()
_LAST = {"speaker": "", "text": "", "time": 0.0}


def record(speaker: str, text: str) -> bool:
    """Append one complete user/assistant turn; deduplicate mirrored UI/STT output."""
    if os.environ.get("NEXUS_ACTIVITY_LOG", "1").strip().lower() in ("0", "false", "off"):
        return False
    speaker = (speaker or "").strip().upper()
    if speaker not in ("VOCÊ", "GEMINI", "GPT"):
        return False
    body = diag.sanitize(str(text or "").strip())
    if not body:
        return False
    with _LOCK:
        now = time.monotonic()
        if (_LAST["speaker"], _LAST["text"]) == (speaker, body) and now-_LAST["time"] < 15:
            return False
        # Multiline text goes into a single delineated turn. Never log secrets unredacted.
        PATH.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with PATH.open("a", encoding="utf-8") as output:
            output.write(f"\n[{stamp}] {speaker}\n{body}\n")
        _LAST.update(speaker=speaker, text=body, time=now)
        return True


def capture_ui_line(line: str, assistant_name: str = "jarvis") -> bool:
    """Capture only conversation lines emitted by the existing UI logger."""
    value = str(line or "").strip()
    match = re.match(r"(?is)^VOCÊ\s*(?:\([^)]*\))?\s*:\s*(.+)$", value)
    if match:
        return record("VOCÊ", match.group(1))
    match = re.match(r"(?is)^You:\s*(.+)$", value)
    if match:
        return record("VOCÊ", match.group(1))
    # GPT is logged explicitly in full by MainWindow._agent_answer_on_ui.
    prefix = str(assistant_name or "jarvis").strip() or "jarvis"
    match = re.match(r"(?is)^(?:" + re.escape(prefix) + r"|JARVIS)\s*:\s*(.+)$", value)
    if match:
        return record("GEMINI", match.group(1))
    return False
