from __future__ import annotations

import base64
import json
import threading
from typing import Callable, Optional, Dict, Any

import io
import numpy as np
import websocket  # websocket-client
from websocket import ABNF
import av  # PyAV for mp3 decoding
import scipy.signal as sps


class WebSocketSTTClient:
    """Generic WebSocket streaming STT client.

    Protocol (example):
    - Client sends JSON {type: "start", sample_rate: 16000}
    - Client streams JSON {type: "audio", audio: base64(pcm16)}
    - Server sends JSON {type: "transcript", text: "...", final: bool}
    - Client sends {type: "stop"} to end
    """

    def __init__(self, url: str, headers: Optional[dict[str, str]] = None, start_payload: Optional[Dict[str, Any]] = None) -> None:
        self.url = url
        self.headers = headers or {}
        self.start_payload = start_payload or {}
        self.ws: Optional[websocket.WebSocketApp] = None
        self.receiver_thread: Optional[threading.Thread] = None
        self._on_transcript: Optional[Callable[[str, bool], None]] = None
        self._on_tts: Optional[Callable[[np.ndarray], None]] = None
        self._on_event: Optional[Callable[[str], None]] = None
        self._ready: bool = False
        self._pending_chunks: list[np.ndarray] = []
        self.provider: str = str(self.start_payload.get("provider", "generic-ws"))
        self.sample_rate: int = 16000

    def start(self, sample_rate: int, on_transcript: Callable[[str, bool], None], on_tts: Optional[Callable[[np.ndarray], None]] = None, extra: Optional[Dict[str, Any]] = None) -> None:
        self._on_transcript = on_transcript
        self._on_tts = on_tts
        self.sample_rate = int(sample_rate)
        if extra and "provider" in extra:
            self.provider = str(extra["provider"]) or self.provider
        if extra and callable(extra.get("on_event")):
            self._on_event = extra.get("on_event")

        def on_open(ws):  # noqa: ANN001
            prov = (self.start_payload.get("provider") or self.provider)
            if self._on_event:
                self._on_event(f"WS open: provider={prov}")
            if prov == "baidu":
                baidu = self.start_payload.get("baidu", {})
                from_lang = (self.start_payload.get("from") or (extra or {}).get("from") or "zh")
                to_lang = (self.start_payload.get("to") or (extra or {}).get("to") or "en")
                msg = {
                    "type": "START",
                    "from": from_lang,
                    "to": to_lang,
                    "app_id": baidu.get("app_id", ""),
                    "app_key": baidu.get("api_key", ""),
                    "sampling_rate": int(self.sample_rate),
                }
                if baidu.get("return_target_tts"):
                    msg["return_target_tts"] = True
                if baidu.get("tts_speaker"):
                    msg["tts_speaker"] = baidu.get("tts_speaker")
                if baidu.get("user_sn"):
                    msg["user_sn"] = baidu.get("user_sn")
                ws.send(json.dumps(msg))
                if self._on_event:
                    self._on_event(f"SEND START: {msg}")
                # Not ready until we receive STA
                self._ready = False
            else:
                payload = {"type": "start", "sample_rate": sample_rate}
                payload.update(self.start_payload or {})
                if extra:
                    payload.update(extra)
                ws.send(json.dumps(payload))
                if self._on_event:
                    self._on_event(f"SEND start: {payload}")
                self._ready = True

        def on_message(ws, message):  # noqa: ANN001
            if self._on_event:
                self._on_event(f"RECV TEXT: {message[:200]}")
            try:
                obj = json.loads(message)
            except Exception:
                return
            prov = (self.start_payload.get("provider") or self.provider)
            if prov == "baidu":
                try:
                    code = int(obj.get("code", -1))
                    if code != 0:
                        return
                    data = obj.get("data") or {}
                    status = data.get("status")
                    if status == "STA":
                        self._ready = True
                        # flush any pending audio
                        if self._pending_chunks:
                            for pending in self._pending_chunks:
                                try:
                                    self.ws.send(pending.tobytes(), opcode=ABNF.OPCODE_BINARY)
                                except Exception:
                                    pass
                            self._pending_chunks.clear()
                    if status == "TRN" and self._on_transcript:
                        res = data.get("result") or {}
                        rtype = res.get("type")
                        if rtype == "MID":
                            text = res.get("asr_trans") or res.get("asr") or ""
                            if text:
                                self._on_transcript(text, False)
                        elif rtype == "FIN":
                            text = res.get("sentence_trans") or res.get("sentence") or ""
                            if text:
                                self._on_transcript(text, True)
                except Exception:
                    pass
            else:
                mtype = obj.get("type")
                if mtype == "transcript" and self._on_transcript:
                    text = obj.get("text", "")
                    is_final = bool(obj.get("final", False))
                    self._on_transcript(text, is_final)
                elif mtype == "tts" and self._on_tts:
                    audio_b64 = obj.get("audio")
                    if audio_b64:
                        try:
                            raw = base64.b64decode(audio_b64)
                            pcm = np.frombuffer(raw, dtype=np.int16)
                            self._on_tts(pcm)
                        except Exception:
                            pass

        def on_data(ws, message, data_type, cont):  # noqa: ANN001
            # For providers like Baidu that return binary TTS frames with first byte as type
            if data_type != ABNF.OPCODE_BINARY or not self._on_tts:
                return
            try:
                if not isinstance(message, (bytes, bytearray)) or len(message) < 2:
                    return
                first = message[0]
                if first != 0x01:
                    return
                mp3_bytes = message[1:]
                pcm = self._decode_mp3_to_pcm16(mp3_bytes, target_sr=self.sample_rate)
                if pcm.size > 0:
                    self._on_tts(pcm)
                if self._on_event:
                    self._on_event(f"RECV BINARY TTS: {len(mp3_bytes)} bytes")
            except Exception:
                pass

        def on_error(ws, error):  # noqa: ANN001
            # Optional: could forward as transcript with error prefix
            if self._on_event:
                self._on_event(f"WS error: {error}")

        def on_close(ws, code, msg):  # noqa: ANN001
            if self._on_event:
                self._on_event(f"WS close: code={code}, msg={msg}")

        header_list = [f"{k}: {v}" for k, v in self.headers.items()]
        self.ws = websocket.WebSocketApp(
            self.url,
            header=header_list,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_data=on_data,
        )

        self.receiver_thread = threading.Thread(target=self.ws.run_forever, kwargs={"ping_interval": 20}, daemon=True)
        self.receiver_thread.start()

    def send_pcm16(self, pcm16: np.ndarray) -> None:
        if self.ws is None:
            return
        if pcm16.ndim > 1:
            pcm16 = pcm16.reshape(-1)
        b = pcm16.astype(np.int16).tobytes()
        try:
            if self.provider == "baidu":
                # Send raw binary audio frame (recommended ~40ms per frame)
                if not self._ready:
                    # queue until we receive STA
                    self._pending_chunks.append(pcm16.copy())
                else:
                    self.ws.send(b, opcode=ABNF.OPCODE_BINARY)
            else:
                payload = {"type": "audio", "audio": base64.b64encode(b).decode("ascii")}
                self.ws.send(json.dumps(payload))
        except Exception:
            pass

    def close(self) -> None:
        try:
            if self.ws:
                try:
                    if (self.start_payload.get("provider") or self.provider) == "baidu":
                        self.ws.send(json.dumps({"type": "FINISH"}))
                    else:
                        self.ws.send(json.dumps({"type": "stop"}))
                except Exception:
                    pass
                self.ws.close()
        finally:
            self.ws = None
            self.receiver_thread = None
            self._ready = False
            self._pending_chunks.clear()

    def _decode_mp3_to_pcm16(self, mp3_bytes: bytes, target_sr: int) -> np.ndarray:
        try:
            with av.open(io.BytesIO(mp3_bytes)) as container:
                stream = next((s for s in container.streams if s.type == "audio"), None)
                if stream is None:
                    return np.zeros((0,), dtype=np.int16)
                frames = []
                for packet in container.demux(stream):
                    for frame in packet.decode():
                        # Convert to planar numpy array float32
                        arr = frame.to_ndarray(format="s16")  # shape: channels x samples
                        if arr.ndim == 2:
                            # average channels to mono
                            pcm = arr.mean(axis=0).astype(np.int16)
                        else:
                            pcm = arr.astype(np.int16)
                        frames.append(pcm)
                if not frames:
                    return np.zeros((0,), dtype=np.int16)
                data = np.concatenate(frames)
                # Resample if needed: frame.sample_rate may be None; we assume 24000/44100 typical
                src_sr = stream.rate or target_sr
                if src_sr != target_sr and data.size > 0:
                    data_f = data.astype(np.float32)
                    num = int(len(data_f) * target_sr / src_sr)
                    data = sps.resample(data_f, num).astype(np.int16)
                return data
        except Exception:
            return np.zeros((0,), dtype=np.int16)




