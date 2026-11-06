"""Non-sensitive, locally persisted NEXUS visual preferences.

Do NOT put API keys here. This configuration is separate from the original
Mark-LVI credential/config file so visual updates never rewrite secrets.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "config" / "nexus_visual.json"
STYLES = ("reactor", "plasma", "orbit", "radar", "neural", "face")
STYLE_LABELS = {
    "reactor": "Reator ARC", "plasma": "Plasma",
    "orbit": "Órbita", "radar": "Radar",
    "neural": "Neural", "face": "Avatar",
}
PRESETS = {
    "Ciano": "#00d5ff", "Violeta": "#a785ff", "Esmeralda": "#32e9b2",
    "Âmbar": "#ffb86b", "Azul": "#5b9eff", "Rosa": "#ff79c6",
}
DEFAULT = {
    "style": "reactor", "accent": PRESETS["Ciano"],
    "intensity": 80, "particles": True, "grid": True,
    "reduced_motion": False, "performance_mode": True, "remote_enabled": False, "weather_city": "",
}
_LOCK = RLock()


def _sanitize(d: object) -> dict:
    d = d if isinstance(d, dict) else {}
    s = DEFAULT.copy()
    if d.get("style") in STYLES:
        s["style"] = d["style"]
    val = str(d.get("accent", ""))
    if len(val) == 7 and val.startswith("#"):
        try:
            int(val[1:], 16)
            s["accent"] = val.lower()
        except ValueError:
            pass
    try:
        s["intensity"] = max(10, min(100, int(d.get("intensity", 80))))
    except (TypeError, ValueError):
        pass
    for k in ("particles", "grid", "reduced_motion", "performance_mode", "remote_enabled"):
        if isinstance(d.get(k), bool):
            s[k] = d[k]
    city = d.get("weather_city", "")
    if isinstance(city, str):
        s["weather_city"] = city.strip()[:100]
    return s


def load() -> dict:
    with _LOCK:
        try:
            return _sanitize(json.loads(PATH.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return DEFAULT.copy()


def save(**updates) -> dict:
    with _LOCK:
        data = _sanitize({**load(), **updates})
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, PATH)
        return data
