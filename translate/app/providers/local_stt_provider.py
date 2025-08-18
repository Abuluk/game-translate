from __future__ import annotations

import collections
from typing import Callable, Optional
import threading
import os

import numpy as np
try:
    from faster_whisper import WhisperModel  # type: ignore
except Exception as e:  # pragma: no cover
    WhisperModel = None  # type: ignore


class LocalStreamingSTT:
    """Local quasi-streaming STT using VAD to segment and faster-whisper to transcribe.

    Notes:
        - Supports optional source language hint (from_lang) to improve accuracy.
        - If target language is English (e.g. "en", "en-US"), will set task="translate" to translate to English.
          Whisper translation only supports translating to English.
    """

    def __init__(self, whisper_model: str = "base", from_lang: Optional[str] = None, to_lang: Optional[str] = None) -> None:
        if WhisperModel is None:
            raise RuntimeError("faster-whisper not available; switch to API 模式或安装依赖/配置镜像后重试")
        try:
            cpu_threads = int(os.getenv("APP_WHISPER_CPU_THREADS", str(os.cpu_count() or 4)))
        except Exception:
            cpu_threads = max(1, (os.cpu_count() or 4))
        try:
            num_workers = int(os.getenv("APP_WHISPER_NUM_WORKERS", "1"))
        except Exception:
            num_workers = 1
        self.model = WhisperModel(
            whisper_model,
            device=os.getenv("APP_WHISPER_DEVICE", "cpu"),
            compute_type=os.getenv("APP_WHISPER_COMPUTE_TYPE", "int8"),
            cpu_threads=cpu_threads,
            num_workers=num_workers,
        )
        self.sample_rate = 16000
        self.frame_ms = 20
        self.frame_size = int(self.sample_rate * self.frame_ms / 1000)
        self._on_transcript: Optional[Callable[[str, bool], None]] = None
        self._on_event: Optional[Callable[[str], None]] = None
        self._buffer = collections.deque()
        self._speech_active = False
        self._silence_count = 0
        # Tunables via env
        try:
            self._silence_threshold = int(os.getenv("APP_LOCAL_VAD_SILENCE_FRAMES", "10"))  # 10 * 20ms = 200ms
        except Exception:
            self._silence_threshold = 10
        try:
            self._energy_threshold = int(os.getenv("APP_LOCAL_VAD_ENERGY", "500"))
        except Exception:
            self._energy_threshold = 500
        self._from_lang = self._normalize_lang(from_lang)
        self._to_lang = self._normalize_lang(to_lang)
        self._frames_in_segment = 0
        try:
            max_ms = int(os.getenv("APP_LOCAL_MAX_SEGMENT_MS", "6000"))
        except Exception:
            max_ms = 6000
        self._max_frames_per_segment = int(max_ms / self.frame_ms)  # force flush ~N seconds
        # Adaptive noise tracking
        try:
            self._noise_update_alpha = float(os.getenv("APP_LOCAL_VAD_NOISE_ALPHA", "0.05"))
        except Exception:
            self._noise_update_alpha = 0.05
        try:
            self._noise_multiplier = float(os.getenv("APP_LOCAL_VAD_NOISE_X", "2.0"))
        except Exception:
            self._noise_multiplier = 2.0
        self._noise_level = 100.0
        self._preview_enabled = False
        self._preview_interval_ms = 800
        self._last_preview_ts = 0.0
        # Async transcription queue
        self._pending = collections.deque()
        self._processing = False
        self._proc_lock = threading.Lock()
        self._proc_thread: Optional[threading.Thread] = None

    def _normalize_lang(self, code: Optional[str]) -> Optional[str]:
        if not code:
            return None
        code_low = code.strip().lower()
        # Map common locale tags to base language
        if code_low.startswith("zh"):
            return "zh"
        if code_low.startswith("en"):
            return "en"
        if code_low.startswith("ja"):
            return "ja"
        if code_low.startswith("ko"):
            return "ko"
        if code_low.startswith("fr"):
            return "fr"
        if code_low.startswith("de"):
            return "de"
        if code_low.startswith("es"):
            return "es"
        if code_low.startswith("ru"):
            return "ru"
        if code_low.startswith("pt"):
            return "pt"
        return code_low

    def start(self, sample_rate: int, on_transcript: Callable[[str, bool], None], on_tts: Optional[Callable[[np.ndarray], None]] = None, extra: Optional[dict] = None) -> None:  # noqa: D401
        self.sample_rate = sample_rate
        self.frame_size = int(self.sample_rate * self.frame_ms / 1000)
        self._on_transcript = on_transcript
        # optional event callback from extra
        try:
            if isinstance(extra, dict) and callable(extra.get("on_event")):
                self._on_event = extra.get("on_event")  # type: ignore
        except Exception:
            self._on_event = None
        # reset state per start
        self._buffer.clear()
        self._speech_active = False
        self._silence_count = 0
        self._frames_in_segment = 0
        try:
            max_ms = int(os.getenv("APP_LOCAL_MAX_SEGMENT_MS", "6000"))
        except Exception:
            max_ms = 6000
        self._max_frames_per_segment = int(max_ms / self.frame_ms) if self.frame_ms > 0 else 300
        # override from extra/config if provided
        try:
            if isinstance(extra, dict):
                vad = extra.get("local_vad") or {}
                en = vad.get("energy_threshold"); sf = vad.get("silence_frames"); msm = vad.get("max_segment_ms"); na = vad.get("noise_alpha"); nx = vad.get("noise_multiplier"); prev = vad.get("preview_enabled"); prev_ms = vad.get("preview_interval_ms")
                if en is not None:
                    self._energy_threshold = int(en)
                if sf is not None:
                    self._silence_threshold = int(sf)
                if msm is not None and self.frame_ms > 0:
                    self._max_frames_per_segment = max(1, int(int(msm) / self.frame_ms))
                if na is not None:
                    self._noise_update_alpha = float(na)
                if nx is not None:
                    self._noise_multiplier = float(nx)
                if prev is not None:
                    self._preview_enabled = bool(prev)
                if prev_ms is not None:
                    self._preview_interval_ms = int(prev_ms)
        except Exception:
            pass
        # debug event
        try:
            from app.workers.stream_workers import BaseStreamWorker  # type: ignore
        except Exception:
            BaseStreamWorker = None  # type: ignore

    def send_pcm16(self, pcm16: np.ndarray) -> None:
        # Split into 20ms frames for VAD
        pcm16 = pcm16.astype(np.int16)
        for i in range(0, len(pcm16), self.frame_size):
            frame = pcm16[i : i + self.frame_size]
            if len(frame) < self.frame_size:
                break
            # Adaptive energy VAD
            level = float(np.mean(np.abs(frame.astype(np.int32))))
            if not self._speech_active:
                self._noise_level = (1.0 - self._noise_update_alpha) * self._noise_level + self._noise_update_alpha * level
            dyn_thresh = max(self._energy_threshold, self._noise_level * self._noise_multiplier)
            is_speech = bool(level > dyn_thresh)
            if is_speech:
                self._buffer.append(frame.copy())
                self._speech_active = True
                self._silence_count = 0
                self._frames_in_segment += 1
                if self._on_event and self._frames_in_segment == 1:
                    try:
                        self._on_event(f"VAD start level={level:.1f} thr={dyn_thresh:.1f}")
                    except Exception:
                        pass
                # debug: long segment flush
                if self._frames_in_segment >= self._max_frames_per_segment:
                    # Force flush long-running speech to avoid never-ending segments
                    self._flush_segment()
                    self._speech_active = False
                    self._silence_count = 0
            else:
                if self._speech_active:
                    self._silence_count += 1
                    if self._silence_count >= self._silence_threshold:
                        # end of utterance
                        self._flush_segment()
                        self._speech_active = False
                        self._silence_count = 0
                        if self._on_event:
                            try:
                                self._on_event("VAD end")
                            except Exception:
                                pass

    def _flush_segment(self) -> None:
        if not self._buffer:
            return
        import numpy as np

        data = np.concatenate(list(self._buffer), axis=0)
        self._buffer.clear()
        # enqueue for background transcription
        self._schedule_transcribe(data)
        self._frames_in_segment = 0
        # partial preview (optional)
        if self._preview_enabled and self._on_transcript:
            import time
            now = time.time()
            if now - self._last_preview_ts >= max(0.05, self._preview_interval_ms / 1000.0):
                try:
                    # Quick low-cost preview with smaller window
                    # Note: For performance, we only take the tail portion
                    tail_ms = min(1000, self._preview_interval_ms * 2)
                    tail_frames = max(1, int((tail_ms / 1000.0) * self.sample_rate))
                    tail = data[-tail_frames:]
                    segs, _ = self.model.transcribe(
                        tail.astype(np.float32) / 32768.0,
                        language=language,
                        task=task,
                        beam_size=1,
                        best_of=1,
                        condition_on_previous_text=False,
                        vad_filter=False,
                        word_timestamps=False,
                        temperature=0.0,
                    )
                    partial = " ".join([s.text for s in segs]).strip()
                    if partial:
                        self._on_transcript(partial, False)
                except Exception:
                    pass
                self._last_preview_ts = now
        if self._on_event:
            try:
                self._on_event(f"flush frames={len(data)}")
            except Exception:
                pass

    def _schedule_transcribe(self, data: np.ndarray) -> None:  # type: ignore[name-defined]
        with self._proc_lock:
            self._pending.append(data)
            if not self._processing:
                self._processing = True
                self._proc_thread = threading.Thread(target=self._proc_loop, daemon=True)
                self._proc_thread.start()

    def _proc_loop(self) -> None:
        while True:
            with self._proc_lock:
                if not self._pending:
                    self._processing = False
                    return
                data = self._pending.popleft()
            try:
                task = "translate" if (self._to_lang == "en") else "transcribe"
                language = self._from_lang if self._from_lang not in {None, "auto"} else None
                if self._on_event:
                    try:
                        self._on_event("transcribe start")
                    except Exception:
                        pass
                segments, _ = self.model.transcribe(
                    data.astype(np.float32) / 32768.0,
                    language=language,
                    task=task,
                    beam_size=int(os.getenv("APP_WHISPER_BEAM_SIZE", "1")),
                    best_of=int(os.getenv("APP_WHISPER_BEST_OF", "1")),
                    condition_on_previous_text=False,
                    vad_filter=False,
                    word_timestamps=False,
                    temperature=0.0,
                )
                text = " ".join([seg.text for seg in segments]).strip()
            except Exception as e:
                text = f"[local error] {e}"
            if self._on_transcript and text:
                try:
                    self._on_transcript(text, True)
                except Exception:
                    pass
            if self._on_event:
                try:
                    self._on_event("transcribe done")
                except Exception:
                    pass

    def close(self) -> None:
        # Flush any remaining
        self._flush_segment()


