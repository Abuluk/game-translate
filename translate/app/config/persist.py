from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Optional

from app.config.runtime_config import AppConfig


def _config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "game_translator")
    os.makedirs(path, exist_ok=True)
    return path


def get_config_path() -> str:
    return os.path.join(_config_dir(), "config.json")


def load_persisted_config() -> Optional[AppConfig]:
    path = get_config_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Backward compatible: construct AppConfig by unpacking dicts
        from app.config.runtime_config import STTApiConfig, LocalSTTConfig

        cfg = AppConfig(
            stt_mode=data.get("stt_mode", "api"),
            stt_api=STTApiConfig(**data.get("stt_api", {})),
            local_stt=LocalSTTConfig(**data.get("local_stt", {})),
            target_game_process=data.get("target_game_process", ""),
            enforce_routing=bool(data.get("enforce_routing", False)),
            subtitles_only=bool(data.get("subtitles_only", False)),
        )
        # Optional UI fields
        cfg.target_language = data.get("target_language", cfg.target_language)
        cfg.mic_device_index = data.get("mic_device_index")
        cfg.tts_output_device_index = data.get("tts_output_device_index")
        cfg.loop_device_kind = data.get("loop_device_kind", cfg.loop_device_kind)
        cfg.loop_device_index = data.get("loop_device_index")
        # Overlay
        ov = data.get("overlay") or {}
        try:
            from app.config.runtime_config import OverlayConfig
            cfg.overlay = OverlayConfig(**ov)
        except Exception:
            pass
        return cfg
    except Exception:
        return None


def save_persisted_config(cfg: AppConfig) -> None:
    path = get_config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(cfg), f, ensure_ascii=False, indent=2)
    except Exception:
        pass



