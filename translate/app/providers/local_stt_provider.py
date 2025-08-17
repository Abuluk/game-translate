from __future__ import annotations

import collections
from typing import Callable, Optional

import numpy as np
try:
    from faster_whisper import WhisperModel  # type: ignore
except Exception as e:  # pragma: no cover
    WhisperModel = None  # type: ignore


class LocalStreamingSTT:
    """Local quasi-streaming STT using VAD to segment and faster-whisper to transcribe."""

    def __init__(self, whisper_model: str = "base") -> None:
        if WhisperModel is None:
            raise RuntimeError("faster-whisper not available; switch to API 模式或安装依赖/配置镜像后重试")
        self.model = WhisperModel(whisper_model, device="cpu", compute_type="int8")
        self.sample_rate = 16000
        self.frame_ms = 20
        self.frame_size = int(self.sample_rate * self.frame_ms / 1000)
        self._on_transcript: Optional[Callable[[str, bool], None]] = None
        self._buffer = collections.deque()
        self._speech_active = False
        self._silence_count = 0
        self._silence_threshold = 10  # 200ms
        self._energy_threshold = 500  # simplistic energy gate

    def start(self, sample_rate: int, on_transcript: Callable[[str, bool], None]) -> None:
        self.sample_rate = sample_rate
        self.frame_size = int(self.sample_rate * self.frame_ms / 1000)
        self._on_transcript = on_transcript

    def send_pcm16(self, pcm16: np.ndarray) -> None:
        # Split into 20ms frames for VAD
        pcm16 = pcm16.astype(np.int16)
        for i in range(0, len(pcm16), self.frame_size):
            frame = pcm16[i : i + self.frame_size]
            if len(frame) < self.frame_size:
                break
            # Simple energy-based VAD replacement for portability
            is_speech = bool(np.mean(np.abs(frame.astype(np.int32))) > self._energy_threshold)
            if is_speech:
                self._buffer.append(frame.copy())
                self._speech_active = True
                self._silence_count = 0
            else:
                if self._speech_active:
                    self._silence_count += 1
                    if self._silence_count >= self._silence_threshold:
                        # end of utterance
                        self._flush_segment()
                        self._speech_active = False
                        self._silence_count = 0

    def _flush_segment(self) -> None:
        if not self._buffer:
            return
        import numpy as np

        data = np.concatenate(list(self._buffer), axis=0)
        self._buffer.clear()
        try:
            segments, _ = self.model.transcribe(data.astype(np.float32) / 32768.0, language=None)
            text = " ".join([seg.text for seg in segments]).strip()
        except Exception as e:
            text = f"[local error] {e}"
        if self._on_transcript and text:
            self._on_transcript(text, True)

    def close(self) -> None:
        # Flush any remaining
        self._flush_segment()


