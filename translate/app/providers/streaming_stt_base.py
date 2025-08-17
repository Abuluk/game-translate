from __future__ import annotations

from typing import Callable, Protocol, Optional, Dict, Any
import numpy as np


class StreamingSTTSession(Protocol):
    def start(self, sample_rate: int, on_transcript: Callable[[str, bool], None], on_tts: Optional[Callable[[np.ndarray], None]] = None, extra: Optional[Dict[str, Any]] = None) -> None: ...
    def send_pcm16(self, pcm16: np.ndarray) -> None: ...
    def close(self) -> None: ...




