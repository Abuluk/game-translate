from __future__ import annotations

import os
import threading
from typing import Optional
import collections

import numpy as np
import sounddevice as sd
from PySide6 import QtCore
from dotenv import load_dotenv
import scipy.signal as sps

from app.audio.chunker import AudioChunker
from app.audio.loopback_fallback import DefaultLoopbackReader
from app.providers.streaming_stt_base import StreamingSTTSession
from app.providers.ws_stt_provider import WebSocketSTTClient
from app.providers.local_stt_provider import LocalStreamingSTT
from app.config.runtime_config import get_config


def _int_or_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


SAMPLE_RATE = _int_or_env("APP_SAMPLE_RATE", 16000)
FRAME_MS = _int_or_env("APP_FRAME_MS", 50)


def _resample_pcm16(pcm: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate or pcm.size == 0:
        return pcm
    data_f = pcm.astype(np.float32)
    num = int(len(data_f) * dst_rate / src_rate)
    out = sps.resample(data_f, num)
    return np.clip(out, -32768, 32767).astype(np.int16)


class BaseStreamWorker(QtCore.QThread):
    message = QtCore.Signal(str)
    status = QtCore.Signal(str)
    event = QtCore.Signal(str)

    def __init__(self, target_lang: str) -> None:
        super().__init__()
        load_dotenv(override=False)
        self._stop_event = threading.Event()
        self.target_lang = target_lang
        self.chunker = AudioChunker(SAMPLE_RATE, FRAME_MS, chunk_frames=20, overlap_frames=5)
        self.stt_session: Optional[StreamingSTTSession] = None

    def _start_system_session(self) -> None:
        cfg = get_config()
        if cfg.stt_mode == "local":
            self.stt_session = LocalStreamingSTT(cfg.local_stt.whisper_model)
        else:
            if not cfg.stt_api.websocket_url:
                self.message.emit("[WS] 未配置 WebSocket URL（模式=api），请在‘识别来源’填写 WS URL 后再开始")
                raise RuntimeError("ws_url_missing")
            headers = {}
            if cfg.stt_api.auth_token:
                headers[cfg.stt_api.auth_header or "Authorization"] = cfg.stt_api.auth_token
            start_payload = {
                "provider": cfg.stt_api.provider,
                "model": cfg.stt_api.model,
                "from": cfg.stt_api.from_lang,
                "to": cfg.stt_api.to_lang,
                "baidu": {
                    "app_id": cfg.stt_api.baidu_app_id,
                    "api_key": cfg.stt_api.baidu_api_key,
                    "secret_key": cfg.stt_api.baidu_secret_key,
                    "return_target_tts": cfg.stt_api.baidu_return_target_tts,
                    "tts_speaker": cfg.stt_api.baidu_tts_speaker,
                    "user_sn": cfg.stt_api.baidu_user_sn,
                },
                "audio_format": {
                    "encoding": "pcm16le",
                    "channels": 1,
                    "sampling_rate": int(cfg.stt_api.sample_rate or SAMPLE_RATE),
                },
                "enable_tts": True,
                "enable_translate": True,
            }
            self.stt_session = WebSocketSTTClient(cfg.stt_api.websocket_url, headers=headers, start_payload=start_payload)

        def on_tr(text: str, is_final: bool) -> None:
            if not text:
                return
            self.message.emit(f"[系统] {text}")

        cfg_sr = max(8000, min(44100, int(get_config().stt_api.sample_rate or SAMPLE_RATE)))
        self.stt_session.start(
            cfg_sr,
            on_tr,
            None,
            {
                "target_lang": self.target_lang,
                "provider": cfg.stt_api.provider,
                "from": cfg.stt_api.from_lang,
                "to": cfg.stt_api.to_lang,
                "on_event": self.message.emit,
            },
        )

    def stop(self) -> None:
        self._stop_event.set()
        self.wait(1000)


class SystemStreamWorker(BaseStreamWorker):
    def __init__(self, loopback_output_device_index: int | tuple, target_lang: str, tts_output_device_index: Optional[int] = None) -> None:
        super().__init__(target_lang)
        # Accept either raw index or (kind, index)
        if isinstance(loopback_output_device_index, tuple):
            self.device_kind, self.device_index = loopback_output_device_index
        else:
            self.device_kind, self.device_index = "output", loopback_output_device_index
        # Optional: system stream TTS playback target (not required)
        self.sys_out_device_index = tts_output_device_index

    def run(self) -> None:
        self.status.emit("系统翻译已启动")

        # Will be set later when device is opened
        capture_rate_holder = {"sr": SAMPLE_RATE}
        api_rate_holder = {"sr": max(8000, min(44100, int(get_config().stt_api.sample_rate or SAMPLE_RATE)))}

        def callback(indata, frames, time, status):  # noqa: ARG001
            if self._stop_event.is_set():
                raise sd.CallbackStop
            # Downmix to mono if multi-channel
            if indata.ndim == 2 and indata.shape[1] > 1:
                mono = indata.mean(axis=1)
            else:
                mono = indata[:, 0] if indata.ndim == 2 else indata
            pcm = (mono * 32767.0).astype(np.int16)
            for chunk in self.chunker.add_frame(pcm):
                try:
                    if not self.stt_session:
                        continue
                    # Resample to API rate if needed
                    src_sr = capture_rate_holder["sr"]
                    dst_sr = api_rate_holder["sr"]
                    if src_sr != dst_sr:
                        chunk = _resample_pcm16(chunk, src_sr, dst_sr)
                    # Ensure <= 40ms per frame
                    max_samples = int(dst_sr * 40 / 1000)
                    start = 0
                    while start < len(chunk):
                        end = min(start + max_samples, len(chunk))
                        self.stt_session.send_pcm16(chunk[start:end])
                        start = end
                except Exception as e:
                    self.status.emit(f"系统翻译错误: {e}")

        # Note: For WASAPI loopback, provide extra_settings=WasapiSettings(loopback=True)
        extra_settings = None
        try:
            dev = sd.query_devices(self.device_index)
            hostapi = sd.query_hostapis(dev["hostapi"]) if dev and "hostapi" in dev else None
            if hostapi and "wasapi" in str(hostapi.get("name", "")).lower() and getattr(self, "device_kind", "output") == "output":
                extra_settings = sd.WasapiSettings(loopback=True)
        except Exception:
            extra_settings = None

        try:
            # Attempt native PortAudio path first; if it fails, fallback to soundcard default loopback
            try:
                # Determine supported channels; for WASAPI loopback, use output channels of the device
                chosen_channels = None
                candidates = []
                try:
                    dev_info = sd.query_devices(self.device_index)
                    hostapi = sd.query_hostapis(dev_info["hostapi"]) if dev_info and "hostapi" in dev_info else None
                    if hostapi and "wasapi" in str(hostapi.get("name", "")).lower():
                        max_out = int(dev_info.get("max_output_channels", 2) or 2)
                        candidates = [max_out, 2, 1]
                        self.message.emit(f"WASAPI loopback 设备输出通道: {max_out}，尝试声道: {candidates}")
                    else:
                        max_in = int(dev_info.get("max_input_channels", 1) or 1)
                        candidates = [max_in, 2, 1]
                        self.message.emit(f"输入设备最大通道: {max_in}，尝试声道: {candidates}")
                except Exception as e:
                    candidates = [2, 1]
                    self.message.emit(f"通道检测失败，回退尝试声道: {candidates}，原因: {e}")

                for ch in [c for c in candidates if c and c > 0]:
                    try:
                        sd.check_input_settings(
                            device=self.device_index,
                            samplerate=int(dev_info.get("default_samplerate") or SAMPLE_RATE),
                            channels=ch,
                            dtype="float32",
                            extra_settings=extra_settings,
                        )
                        chosen_channels = ch
                        break
                    except Exception as ce:
                        self.message.emit(f"声道 {ch} 不可用: {ce}")

                if not chosen_channels:
                    raise RuntimeError("no_channel")

                capture_rate = int(dev_info.get("default_samplerate") or 44100)
                self.message.emit(f"系统捕获采样率: {capture_rate}")
                # For streaming WS (e.g., Baidu) use ~40ms frames to avoid oversize frames
                send_ms = 40
                self.chunker = AudioChunker(capture_rate, send_ms, chunk_frames=1, overlap_frames=0)
                capture_rate_holder["sr"] = capture_rate

                with sd.InputStream(
                    device=self.device_index,
                    samplerate=capture_rate,
                    channels=chosen_channels,
                    dtype="float32",
                    blocksize=int(capture_rate * FRAME_MS / 1000),
                    callback=callback,
                    extra_settings=extra_settings,
                ):
                    # Run system session main loop for native path
                    self._start_system_session()
                    while not self._stop_event.is_set():
                        self.msleep(50)
                    try:
                        if self.stt_session:
                            self.stt_session.close()
                    finally:
                        self.stt_session = None
            except Exception as primary_err:
                self.message.emit(f"主回环打开失败，尝试默认扬声器回环：{primary_err}")
                # Fallback: capture default speaker via soundcard library
                fallback_rate = 44100
                send_ms = 40
                block = int(fallback_rate * send_ms / 1000)
                self.chunker = AudioChunker(fallback_rate, send_ms, chunk_frames=1, overlap_frames=0)
                with DefaultLoopbackReader(fallback_rate, block) as reader:
                    # Launch session
                    self._start_system_session()
                    capture_rate_holder["sr"] = fallback_rate
                    while not self._stop_event.is_set():
                        pcm = reader.read()
                        for chunk in self.chunker.add_frame(pcm):
                            try:
                                if self.stt_session:
                                    # Resample to API SR if needed
                                    api_sr = api_rate_holder["sr"]
                                    if api_sr != fallback_rate:
                                        chunk = _resample_pcm16(chunk, fallback_rate, api_sr)
                                    # Segment to <= 40ms
                                    max_samples = int(api_sr * 40 / 1000)
                                    start = 0
                                    while start < len(chunk):
                                        end = min(start + max_samples, len(chunk))
                                        self.stt_session.send_pcm16(chunk[start:end])
                                        start = end
                            except Exception as e:
                                self.status.emit(f"系统翻译错误: {e}")
                        self.msleep(5)
                    try:
                        if self.stt_session:
                            self.stt_session.close()
                    finally:
                        self.stt_session = None
                # Prepare streaming session (noop here since already started)
                cfg = get_config()
                if cfg.stt_mode == "api" and cfg.stt_api.websocket_url:
                    headers = {}
                    if cfg.stt_api.auth_token:
                        headers[cfg.stt_api.auth_header or "Authorization"] = cfg.stt_api.auth_token
                    start_payload = {
                        "provider": cfg.stt_api.provider,
                        "model": cfg.stt_api.model,
                        "from": cfg.stt_api.from_lang,
                        "to": cfg.stt_api.to_lang,
                        "baidu": {
                            "app_id": cfg.stt_api.baidu_app_id,
                            "api_key": cfg.stt_api.baidu_api_key,
                            "secret_key": cfg.stt_api.baidu_secret_key,
                            "return_target_tts": cfg.stt_api.baidu_return_target_tts,
                            "tts_speaker": cfg.stt_api.baidu_tts_speaker,
                            "user_sn": cfg.stt_api.baidu_user_sn,
                        },
                        "audio_format": {
                            "encoding": "pcm16le",
                            "channels": 1,
                            "sampling_rate": int(cfg.stt_api.sample_rate or SAMPLE_RATE),
                        },
                        "enable_tts": True,
                        "enable_translate": True,
                    }
                    self.stt_session = WebSocketSTTClient(cfg.stt_api.websocket_url, headers=headers, start_payload=start_payload)
                else:
                    self.stt_session = LocalStreamingSTT(cfg.local_stt.whisper_model)

                def on_tr(text: str, is_final: bool) -> None:
                    if not text:
                        return
                    self.message.emit(f"[系统] {text}")

                # Use configured sample rate
                cfg_sr = max(8000, min(44100, int(get_config().stt_api.sample_rate or SAMPLE_RATE)))
                self.stt_session.start(
                    cfg_sr,
                    on_tr,
                    None,
                    {
                        "target_lang": self.target_lang,
                        "provider": cfg.stt_api.provider,
                        "from": cfg.stt_api.from_lang,
                        "to": cfg.stt_api.to_lang,
                        "on_event": self.event.emit,
                    },
                )
                while not self._stop_event.is_set():
                    self.msleep(50)
                try:
                    if self.stt_session:
                        self.stt_session.close()
                finally:
                    self.stt_session = None
        except Exception as e:
            self.status.emit(f"系统音频捕获失败: {e}")

        self.status.emit("系统翻译已停止")


class MicStreamWorker(BaseStreamWorker):
    def __init__(self, mic_device_index: int, tts_output_device_index: int, target_lang: str) -> None:
        super().__init__(target_lang)
        self.mic_device_index = mic_device_index
        self.out_device_index = tts_output_device_index

    def run(self) -> None:
        self.status.emit("麦克风翻译已启动")

        playback_queue: collections.deque[np.ndarray] = collections.deque()

        def mic_callback(indata, frames, time, status):  # noqa: ARG001
            if self._stop_event.is_set():
                raise sd.CallbackStop
            if indata.ndim == 2 and indata.shape[1] > 1:
                mono = indata.mean(axis=1)
            else:
                mono = indata[:, 0] if indata.ndim == 2 else indata
            pcm = (mono * 32767.0).astype(np.int16)
            for chunk in self.chunker.add_frame(pcm):
                try:
                    if self.stt_session:
                        self.stt_session.send_pcm16(chunk)
                except Exception as e:
                    self.status.emit(f"麦克风翻译错误: {e}")

        def out_callback(outdata, frames, time, status):  # noqa: ARG001
            if self._stop_event.is_set():
                raise sd.CallbackStop
            outdata.fill(0)
            if playback_queue:
                buf = playback_queue.popleft()
                needed = frames
                if len(buf) > needed:
                    data = buf[:needed]
                    remainder = buf[needed:]
                    playback_queue.appendleft(remainder)
                else:
                    data = buf
                out = (data.astype(np.float32) / 32767.0).reshape(-1, 1)
                outdata[: len(out), 0] = out[:, 0]

        try:
            # Determine mic input channels
            mic_channels = 1
            try:
                dev_info = sd.query_devices(self.mic_device_index)
                max_in = int(dev_info.get("max_input_channels", 1))
                mic_channels = max(1, min(2, max_in))
                self.status.emit(f"麦克风输入通道: {mic_channels}")
            except Exception:
                mic_channels = 1
            with sd.InputStream(
                device=self.mic_device_index,
                samplerate=SAMPLE_RATE,
                channels=mic_channels,
                dtype="float32",
                blocksize=int(SAMPLE_RATE * FRAME_MS / 1000),
                callback=mic_callback,
            ), sd.OutputStream(
                device=self.out_device_index,
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=int(SAMPLE_RATE * FRAME_MS / 1000),
                callback=out_callback,
            ):
                cfg = get_config()
                if cfg.stt_mode == "api" and cfg.stt_api.websocket_url:
                    headers = {}
                    if cfg.stt_api.auth_token:
                        headers[cfg.stt_api.auth_header or "Authorization"] = cfg.stt_api.auth_token
                    start_payload = {
                        "provider": cfg.stt_api.provider,
                        "model": cfg.stt_api.model,
                        "from": cfg.stt_api.from_lang,
                        "to": cfg.stt_api.to_lang,
                        "baidu": {
                            "app_id": cfg.stt_api.baidu_app_id,
                            "api_key": cfg.stt_api.baidu_api_key,
                            "secret_key": cfg.stt_api.baidu_secret_key,
                            "return_target_tts": cfg.stt_api.baidu_return_target_tts,
                            "tts_speaker": cfg.stt_api.baidu_tts_speaker,
                            "user_sn": cfg.stt_api.baidu_user_sn,
                        },
                        "aliyun": {
                            "access_key_id": cfg.stt_api.aliyun_access_key_id,
                            "access_key_secret": cfg.stt_api.aliyun_access_key_secret,
                            "app_key": cfg.stt_api.aliyun_app_key,
                            "endpoint": cfg.stt_api.aliyun_endpoint,
                        },
                        "azure": {
                            "speech_key": cfg.stt_api.azure_speech_key,
                            "region": cfg.stt_api.azure_region,
                            "endpoint": cfg.stt_api.azure_endpoint,
                        },
                        "iflytek": {
                            "app_id": cfg.stt_api.iflytek_app_id,
                            "api_key": cfg.stt_api.iflytek_api_key,
                            "api_secret": cfg.stt_api.iflytek_api_secret,
                        },
                        "audio_format": {
                            "encoding": "pcm16le",
                            "channels": 1,
                            "sampling_rate": int(cfg.stt_api.sample_rate or SAMPLE_RATE),
                        },
                        "enable_tts": True,
                        "enable_translate": True,
                    }
                    self.stt_session = WebSocketSTTClient(cfg.stt_api.websocket_url, headers=headers, start_payload=start_payload)
                else:
                    self.stt_session = LocalStreamingSTT(cfg.local_stt.whisper_model)

                def on_tr(text: str, is_final: bool) -> None:
                    if not text:
                        return
                    self.message.emit(f"[我] {text}")

                def on_tts(pcm: np.ndarray) -> None:
                    if pcm.size > 0:
                        playback_queue.append(pcm.astype(np.int16))

                cfg_sr = max(8000, min(44100, int(get_config().stt_api.sample_rate or SAMPLE_RATE)))
                self.stt_session.start(
                    cfg_sr,
                    on_tr,
                    on_tts,
                    {
                        "target_lang": self.target_lang,
                        "provider": cfg.stt_api.provider,
                        "from": cfg.stt_api.from_lang,
                        "to": cfg.stt_api.to_lang,
                        "on_event": self.event.emit,
                    },
                )
                while not self._stop_event.is_set():
                    self.msleep(20)
                try:
                    if self.stt_session:
                        self.stt_session.close()
                finally:
                    self.stt_session = None
        except Exception as e:
            self.status.emit(f"音频设备错误: {e}")

        self.status.emit("麦克风翻译已停止")


