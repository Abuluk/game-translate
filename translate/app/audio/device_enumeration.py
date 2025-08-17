from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import sounddevice as sd


@dataclass
class AudioDevice:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    hostapi: int
    hostapi_name: str = ""


def get_input_devices() -> List[AudioDevice]:
    devices = []
    for idx, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) > 0:
            hostapi_idx = d.get("hostapi", 0)
            hostapi = sd.query_hostapis(hostapi_idx)
            devices.append(
                AudioDevice(
                    index=idx,
                    name=d.get("name", f"Device {idx}"),
                    max_input_channels=d.get("max_input_channels", 0),
                    max_output_channels=d.get("max_output_channels", 0),
                    hostapi=hostapi_idx,
                    hostapi_name=str(hostapi.get("name", "")) if hostapi else "",
                )
            )
    return devices


def get_output_devices() -> List[AudioDevice]:
    devices = []
    for idx, d in enumerate(sd.query_devices()):
        if d.get("max_output_channels", 0) > 0:
            hostapi_idx = d.get("hostapi", 0)
            hostapi = sd.query_hostapis(hostapi_idx)
            devices.append(
                AudioDevice(
                    index=idx,
                    name=d.get("name", f"Device {idx}"),
                    max_input_channels=d.get("max_input_channels", 0),
                    max_output_channels=d.get("max_output_channels", 0),
                    hostapi=hostapi_idx,
                    hostapi_name=str(hostapi.get("name", "")) if hostapi else "",
                )
            )
    return devices


def get_default_loopback_device() -> Optional[AudioDevice]:
    # On Windows WASAPI loopback maps to output device index; we simply suggest default output
    try:
        default_out = sd.default.device[1]  # (in, out)
        if default_out is None:
            return None
        info = sd.query_devices(default_out)
        return AudioDevice(
            index=default_out,
            name=info.get("name", f"Device {default_out}"),
            max_input_channels=info.get("max_input_channels", 0),
            max_output_channels=info.get("max_output_channels", 0),
            hostapi=info.get("hostapi", 0),
        )
    except Exception:
        return None


def get_stereo_mix_devices() -> List[AudioDevice]:
    """Return input devices that look like system mix/loopback capture (Stereo Mix/What U Hear)."""
    keywords = [
        "stereo mix",
        "stereomix",
        "what u hear",
        "wave out mix",
        "loopback",
        "立体声混音",
    ]
    devices: List[AudioDevice] = []
    for idx, d in enumerate(sd.query_devices()):
        name = str(d.get("name", ""))
        if d.get("max_input_channels", 0) <= 0:
            continue
        lname = name.lower()
        if any(k in lname for k in keywords):
            hostapi_idx = d.get("hostapi", 0)
            hostapi = sd.query_hostapis(hostapi_idx)
            devices.append(
                AudioDevice(
                    index=idx,
                    name=name,
                    max_input_channels=d.get("max_input_channels", 0),
                    max_output_channels=d.get("max_output_channels", 0),
                    hostapi=hostapi_idx,
                    hostapi_name=str(hostapi.get("name", "")) if hostapi else "",
                )
            )
    return devices





