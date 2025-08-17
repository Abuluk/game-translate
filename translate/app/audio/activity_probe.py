from __future__ import annotations

from typing import List, Dict

import numpy as np
import soundcard as sc


def probe_speakers_activity(duration_sec: float = 0.3, sample_rate: int = 44100) -> List[Dict[str, object]]:
    """Probe all speakers' loopback activity using soundcard.

    Returns list of {name, rms, channels} sorted by rms desc.
    """
    speakers = sc.all_speakers()
    num_frames = int(sample_rate * duration_sec)
    results: List[Dict[str, object]] = []
    for spk in speakers:
        try:
            mic = sc.get_microphone(str(spk.name), include_loopback=True)
            if mic is None:
                continue
            with mic.recorder(samplerate=sample_rate, channels=2) as rec:
                data = rec.record(num_frames)
                # RMS energy across channels
                if data.size == 0:
                    rms = 0.0
                    chans = 0
                else:
                    chans = data.shape[1] if data.ndim == 2 else 1
                    mono = data.mean(axis=1) if data.ndim == 2 else data
                    rms = float(np.sqrt(np.mean(mono.astype(np.float32) ** 2)))
            results.append({"name": spk.name, "rms": rms, "channels": chans})
        except Exception:
            continue
    results.sort(key=lambda x: x["rms"], reverse=True)
    return results



