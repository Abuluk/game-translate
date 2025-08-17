from __future__ import annotations

import numpy as np
import soundcard as sc


class DefaultLoopbackReader:
    """Fallback loopback reader using `soundcard` to capture default speaker output.

    Note: This is a fallback when PortAudio/wasapi fails. It captures system mix
    from the default speaker using WASAPI loopback under the hood.
    """

    def __init__(self, sample_rate: int, block_size: int):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.spk = sc.default_speaker()
        self.mic = None
        self.stream = None

    def __enter__(self):
        # Find loopback microphone corresponding to default speaker
        try:
            self.mic = sc.get_microphone(str(self.spk.name), include_loopback=True)
        except Exception:
            # Fallback: pick any loopback mic
            loopbacks = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
            self.mic = loopbacks[0] if loopbacks else None
        if self.mic is None:
            raise RuntimeError("No loopback microphone found for default speaker")
        self.stream = self.mic.recorder(samplerate=self.sample_rate, channels=2)
        self.stream.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.stream is not None:
            self.stream.__exit__(exc_type, exc, tb)
            self.stream = None

    def read(self) -> np.ndarray:
        if self.stream is None:
            return np.zeros((0,), dtype=np.int16)
        data = self.stream.record(self.block_size)
        # downmix to mono
        if data.ndim == 2:
            mono = data.mean(axis=1)
        else:
            mono = data
        pcm = np.clip(mono, -1.0, 1.0)
        return (pcm * 32767.0).astype(np.int16)


