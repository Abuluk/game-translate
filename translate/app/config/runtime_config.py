from __future__ import annotations

import os
from dataclasses import dataclass, field
from threading import RLock


@dataclass
class STTApiConfig:
    websocket_url: str = ""
    auth_header: str = "Authorization"
    auth_token: str = ""
    # Provider selection: generic-ws | baidu | aliyun | azure | iflytek
    provider: str = "generic-ws"
    # Common model field (optional)
    model: str = ""
    # Sample rate for streaming (8000, 16000, 44100)
    sample_rate: int = 16000
    # Language directions (provider-dependent; used by baidu)
    from_lang: str = "zh"
    to_lang: str = "en"
    # Streaming controls
    heartbeat_interval_sec: float = 5.0
    frame_ms: int = 40
    # Baidu-specific options
    baidu_return_target_tts: bool = False
    baidu_tts_speaker: str = "man"
    baidu_user_sn: str = ""
    # Baidu credentials
    baidu_app_id: str = ""
    baidu_api_key: str = ""
    baidu_secret_key: str = ""
    # Aliyun credentials
    aliyun_access_key_id: str = ""
    aliyun_access_key_secret: str = ""
    aliyun_app_key: str = ""
    aliyun_endpoint: str = ""
    # Azure credentials
    azure_speech_key: str = ""
    azure_region: str = ""
    azure_endpoint: str = ""
    # iFlytek credentials
    iflytek_app_id: str = ""
    iflytek_api_key: str = ""
    iflytek_api_secret: str = ""




@dataclass
class LocalSTTConfig:
    whisper_model: str = "base"


@dataclass
class LocalTTSConfig:
    tts_model_dir: str = ""


@dataclass
class LocalGGUFConfig:
    whisper_cpp_exe: str = ""  # path to whisper.cpp executable (main.exe)
    whisper_cpp_model: str = ""  # path to .gguf model file


@dataclass
class LocalVadConfig:
    energy_threshold: int = 500
    silence_frames: int = 10
    max_segment_ms: int = 6000
    noise_alpha: float = 0.05
    noise_multiplier: float = 2.0
    preview_enabled: bool = False
    preview_interval_ms: int = 800


@dataclass
class OverlayConfig:
    font_size: int = 28
    color_hex: str = "#FFFFFF"
    bg_opacity: float = 0.0
    # Percent-based geometry relative to primary screen
    x_pct: float = 0.1
    y_pct: float = 0.76
    width_pct: float = 0.8
    height_pct: float = 0.18


@dataclass
class AppConfig:
    # stt_mode: 'api' (websocket true streaming) or 'local'
    stt_mode: str = "api"  # values: api | local | local-gguf
    stt_api: STTApiConfig = field(default_factory=STTApiConfig)
    local_stt: LocalSTTConfig = field(default_factory=LocalSTTConfig)
    local_tts: LocalTTSConfig = field(default_factory=LocalTTSConfig)
    local_vad: LocalVadConfig = field(default_factory=LocalVadConfig)
    local_gguf: LocalGGUFConfig = field(default_factory=LocalGGUFConfig)
    # Game targeting
    target_game_process: str = ""  # e.g. game.exe
    enforce_routing: bool = False   # hint UI to remind routing
    # Translation/TTS providers
    use_openai_translation: bool = True
    use_openai_tts: bool = True
    # Subtitles only mode: do not require mic or TTS devices
    subtitles_only: bool = False
    # UI preferences / persisted selections
    target_language: str = "zh-CN"
    mic_device_index: int | None = None
    tts_output_device_index: int | None = None
    loop_device_kind: str = "output"  # 'output' or 'input'
    loop_device_index: int | None = None
    overlay: OverlayConfig = field(default_factory=OverlayConfig)


_lock = RLock()
_config = AppConfig(
    stt_mode=(lambda v: v if v in {"api", "local", "local-gguf"} else ("api" if v in {"api", "websocket"} else "local"))(os.getenv("APP_STT_MODE", "api").lower()),
    stt_api=STTApiConfig(
        websocket_url=os.getenv("STT_WS_URL", ""),
        auth_header=os.getenv("STT_WS_AUTH_HEADER", "Authorization"),
        auth_token=os.getenv("STT_WS_AUTH_TOKEN", ""),
        provider=os.getenv("STT_PROVIDER", "generic-ws"),
        model=os.getenv("STT_MODEL", ""),
        sample_rate=int(os.getenv("STT_SAMPLE_RATE", "16000") or 16000),
        from_lang=os.getenv("STT_FROM_LANG", "zh"),
        to_lang=os.getenv("STT_TO_LANG", "en"),
        heartbeat_interval_sec=float(os.getenv("STT_HEARTBEAT_SEC", "5.0") or 5.0),
        frame_ms=int(os.getenv("STT_FRAME_MS", "40") or 40),
        baidu_return_target_tts=os.getenv("BAIDU_RETURN_TARGET_TTS", "false").lower() in {"1", "true", "yes"},
        baidu_tts_speaker=os.getenv("BAIDU_TTS_SPEAKER", "man"),
        baidu_user_sn=os.getenv("BAIDU_USER_SN", ""),
        baidu_app_id=os.getenv("BAIDU_APP_ID", ""),
        baidu_api_key=os.getenv("BAIDU_API_KEY", ""),
        baidu_secret_key=os.getenv("BAIDU_SECRET_KEY", ""),
        aliyun_access_key_id=os.getenv("ALIYUN_ACCESS_KEY_ID", ""),
        aliyun_access_key_secret=os.getenv("ALIYUN_ACCESS_KEY_SECRET", ""),
        aliyun_app_key=os.getenv("ALIYUN_APP_KEY", ""),
        aliyun_endpoint=os.getenv("ALIYUN_ENDPOINT", ""),
        azure_speech_key=os.getenv("AZURE_SPEECH_KEY", ""),
        azure_region=os.getenv("AZURE_REGION", ""),
        azure_endpoint=os.getenv("AZURE_ENDPOINT", ""),
        iflytek_app_id=os.getenv("IFLYTEK_APP_ID", ""),
        iflytek_api_key=os.getenv("IFLYTEK_API_KEY", ""),
        iflytek_api_secret=os.getenv("IFLYTEK_API_SECRET", ""),
    ),
    local_stt=LocalSTTConfig(
        whisper_model=os.getenv("LOCAL_WHISPER_MODEL", "base"),
    ),
    local_tts=LocalTTSConfig(
        tts_model_dir=os.getenv("LOCAL_TTS_MODEL_DIR", ""),
    ),
    local_gguf=LocalGGUFConfig(
        whisper_cpp_exe=os.getenv("WHISPER_CPP_EXE", ""),
        whisper_cpp_model=os.getenv("WHISPER_CPP_MODEL", ""),
    ),
    local_vad=LocalVadConfig(
        energy_threshold=int(os.getenv("APP_LOCAL_VAD_ENERGY", "500") or 500),
        silence_frames=int(os.getenv("APP_LOCAL_VAD_SILENCE_FRAMES", "10") or 10),
        max_segment_ms=int(os.getenv("APP_LOCAL_MAX_SEGMENT_MS", "6000") or 6000),
        noise_alpha=float(os.getenv("APP_LOCAL_VAD_NOISE_ALPHA", "0.05") or 0.05),
        noise_multiplier=float(os.getenv("APP_LOCAL_VAD_NOISE_X", "2.0") or 2.0),
        preview_enabled=os.getenv("APP_LOCAL_PREVIEW", "false").lower() in {"1", "true", "yes"},
        preview_interval_ms=int(os.getenv("APP_LOCAL_PREVIEW_MS", "800") or 800),
    ),
    target_game_process=os.getenv("TARGET_GAME_PROCESS", ""),
    enforce_routing=os.getenv("ENFORCE_ROUTING", "false").lower() in {"1", "true", "yes"},
    use_openai_translation=os.getenv("USE_OPENAI_TRANSLATION", "true").lower() in {"1", "true", "yes"},
    use_openai_tts=os.getenv("USE_OPENAI_TTS", "true").lower() in {"1", "true", "yes"},
    subtitles_only=os.getenv("SUBTITLES_ONLY", "false").lower() in {"1", "true", "yes"},
    target_language=os.getenv("APP_LANGUAGE_TARGET", "zh-CN"),
)


def get_config() -> AppConfig:
    with _lock:
        return _config


def update_config(new_config: AppConfig) -> None:
    global _config
    with _lock:
        _config = new_config


