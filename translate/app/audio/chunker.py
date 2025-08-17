from __future__ import annotations

import collections
from typing import Deque, Iterable, List

import numpy as np


class AudioChunker:
    """Fixed-size frame collector that yields overlapped chunks for low latency."""

    def __init__(self, sample_rate: int, frame_ms: int = 50, chunk_frames: int = 20, overlap_frames: int = 5) -> None:
        self.sample_rate = sample_rate
        self.frame_size = int(sample_rate * frame_ms / 1000)
        self.chunk_frames = chunk_frames
        self.overlap_frames = overlap_frames
        self.buffer: Deque[np.ndarray] = collections.deque()

    def add_frame(self, frame: np.ndarray) -> List[np.ndarray]:
        self.buffer.append(frame)
        chunks: List[np.ndarray] = []
        while len(self.buffer) >= self.chunk_frames:
            # Gather chunk
            frames = list(self.buffer)[: self.chunk_frames]
            chunk = np.concatenate(frames, axis=0)
            chunks.append(chunk)
            # Slide by (chunk - overlap)
            for _ in range(self.chunk_frames - self.overlap_frames):
                self.buffer.popleft()
        return chunks

    def feed(self, frames: Iterable[np.ndarray]) -> Iterable[np.ndarray]:
        for f in frames:
            for c in self.add_frame(f):
                yield c







