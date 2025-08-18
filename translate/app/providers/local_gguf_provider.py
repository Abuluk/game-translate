from __future__ import annotations

import subprocess
import shutil
import tempfile
from typing import Callable, Optional, List
import threading
import os
import numpy as np

from app.providers.streaming_stt_base import StreamingSTTSession


class WhisperCppSession(StreamingSTTSession):
    """Minimal wrapper to stream PCM16 to whisper.cpp process.

    Implementation notes:
    - Uses a background thread to feed stdin with 16kHz mono PCM16 data as WAV.
    - To keep dependencies minimal and fully offline, we write a temporary WAV file chunk-wise.
      For simplicity and robustness (and because whisper.cpp expects files), we will buffer to a temp WAV
      and call the binary repeatedly per utterance. A basic energy VAD is used to segment speech.
    - This mirrors the local faster-whisper provider's approach for segmentation.
    """

    def __init__(self, exe_path: str, model_path: str, from_lang: Optional[str], to_lang: Optional[str]) -> None:
        if not exe_path or not os.path.isfile(exe_path):
            raise RuntimeError("whisper.cpp 可执行文件路径无效")
        if not model_path or not os.path.isfile(model_path):
            raise RuntimeError("whisper.cpp 模型(.gguf)路径无效")
        self.exe_path = exe_path
        self.model_path = model_path
        self.from_lang = (from_lang or "").lower() or None
        self.to_lang = (to_lang or "").lower() or None
        self.sample_rate = 16000
        self.frame_ms = 20
        self.frame_size = int(self.sample_rate * self.frame_ms / 1000)
        self._on_transcript: Optional[Callable[[str, bool], None]] = None
        self._buffer: List[np.ndarray] = []
        self._speech_active = False
        self._silence_count = 0
        self._silence_threshold = 10
        self._energy_threshold = 500
        self._lock = threading.Lock()

    def start(self, sample_rate: int, on_transcript: Callable[[str, bool], None], on_tts: Optional[Callable[[np.ndarray], None]] = None, extra: Optional[dict] = None) -> None:  # noqa: D401
        self.sample_rate = sample_rate
        self.frame_size = int(self.sample_rate * self.frame_ms / 1000)
        self._on_transcript = on_transcript

    def send_pcm16(self, pcm16: np.ndarray) -> None:
        pcm16 = pcm16.astype(np.int16)
        for i in range(0, len(pcm16), self.frame_size):
            frame = pcm16[i : i + self.frame_size]
            if len(frame) < self.frame_size:
                break
            is_speech = bool(np.mean(np.abs(frame.astype(np.int32))) > self._energy_threshold)
            if is_speech:
                with self._lock:
                    self._buffer.append(frame.copy())
                self._speech_active = True
                self._silence_count = 0
            else:
                if self._speech_active:
                    self._silence_count += 1
                    if self._silence_count >= self._silence_threshold:
                        self._flush_segment()
                        self._speech_active = False
                        self._silence_count = 0

    def _flush_segment(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            data = np.concatenate(self._buffer, axis=0)
            self._buffer.clear()
        # Write to temp wav
        tmpdir = tempfile.mkdtemp(prefix="wcpp_")
        wav_path = os.path.join(tmpdir, "seg.wav")
        try:
            import soundfile as sf
            sf.write(wav_path, data.astype(np.float32) / 32768.0, self.sample_rate, subtype="PCM_16")
        except Exception as e:
            if self._on_transcript:
                self._on_transcript(f"[whisper.cpp 写入wav失败] {e}", True)
            shutil.rmtree(tmpdir, ignore_errors=True)
            return

        # Build command
        args = [self.exe_path, "-m", self.model_path, "-f", wav_path, "-np"]
        # language/source
        if self.from_lang and self.from_lang not in {"auto", ""}:
            args += ["-l", self.from_lang]
        # translation to English if requested
        if self.to_lang and self.to_lang.startswith("en"):
            args += ["-tr"]

        try:
            out = subprocess.check_output(args, stderr=subprocess.STDOUT, text=True)
            # naive parse: take last non-empty line
            lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
            if lines:
                text = lines[-1]
                if self._on_transcript and text:
                    self._on_transcript(text, True)
        except subprocess.CalledProcessError as e:
            if self._on_transcript:
                self._on_transcript(f"[whisper.cpp 失败] {e.output}", True)
        except Exception as e:
            if self._on_transcript:
                self._on_transcript(f"[whisper.cpp 错误] {e}", True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def close(self) -> None:
        # flush remaining
        self._flush_segment()



