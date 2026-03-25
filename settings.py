"""App settings: load/save user preferences to settings.json."""

import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent / "settings.json"

LANGUAGES = {
    "ja-JP": {"name": "Japanese", "short": "ja", "font": "Yu Gothic UI", "has_romaji": True},
    "en-US": {"name": "English", "short": "en", "font": "Segoe UI", "has_romaji": False},
}

DEFAULTS = {
    "overlay_font_size": 16,
    "overlay_opacity": 90,
    "overlay_max_history": 3,
    "overlay_x": -1,
    "overlay_y": -1,
    "overlay_width": -1,
    "overlay_height": -1,
    "energy_threshold": 200,
    "interview_language": "ja-JP",
    "azure_speech_key": "",
    "azure_speech_region": "",
    "azure_openai_key": "",
    "azure_openai_endpoint": "",
    "azure_openai_deployment": "",
    "azure_openai_fast_deployment": "",
    "azure_translator_key": "",
    "azure_translator_region": "",
}


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(DEFAULTS)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)


def save_settings(settings: dict):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
