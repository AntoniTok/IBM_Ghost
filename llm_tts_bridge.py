#!/usr/bin/env python3
"""
llm_tts_bridge.py — Connect your LLM's output directly to Piper TTS.

Import this module in your LLM application to speak responses aloud.
The voice is loaded once at startup for low latency on subsequent calls.

Example usage:
    from llm_tts_bridge import TTSBridge

    tts = TTSBridge()
    tts.speak("Good morning!")

    # Or stream token by token — bridge buffers until a sentence is complete:
    for token in my_llm.stream("Tell me about the weather"):
        tts.stream_token(token)
    tts.flush()
"""

import os
import re
import threading
import time

import numpy as np
import requests
import sounddevice as sd
from piper.voice import PiperVoice

try:
    from piper.voice import SynthesisConfig
    _HAS_SYN_CONFIG = True
except ImportError:
    _HAS_SYN_CONFIG = False

from config import PIPER_MODEL, PIPER_CONFIG, PIPER_LENGTH_SCALE, PIPER_SENTENCE_PAUSE

_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')

# ─── Face-state push (drives the kiosk SVG ghost) ────────────────────────────
# When TTS starts, we POST {"state":"speaking"} to sentinel_api so the kiosk
# page on the AMOLED grows the ghost. When TTS finishes, we POST
# {"state":"idle"} so it shrinks back. A short debounce on "idle" prevents
# flicker between rapid back-to-back speak() calls (e.g. thinking phrase ->
# LLM reply).
_FACE_STATE_URL = os.environ.get(
    "GHOST_FACE_STATE_URL",
    "http://127.0.0.1:8080/api/face/state",
)
_FACE_IDLE_DEBOUNCE = 0.4  # seconds: hold "speaking" briefly after speech ends
_face_lock = threading.Lock()
_face_idle_timer: "threading.Timer | None" = None
_face_current = "idle"


def _push_face_state(state: str) -> None:
    """Fire-and-forget POST to the face-state endpoint. Never raises."""
    try:
        requests.post(_FACE_STATE_URL, json={"state": state}, timeout=0.4)
    except Exception:
        # The face is decoration — if sentinel_api is down, swallow.
        pass


def _set_speaking() -> None:
    """Mark face speaking and cancel any pending idle transition."""
    global _face_current, _face_idle_timer
    with _face_lock:
        if _face_idle_timer is not None:
            _face_idle_timer.cancel()
            _face_idle_timer = None
        if _face_current == "speaking":
            return
        _face_current = "speaking"
    _push_face_state("speaking")


def _set_idle_soon() -> None:
    """Schedule transition back to idle after a short debounce."""
    global _face_current, _face_idle_timer

    def _flush_idle():
        global _face_current, _face_idle_timer
        with _face_lock:
            _face_idle_timer = None
            if _face_current == "idle":
                return
            _face_current = "idle"
        _push_face_state("idle")

    with _face_lock:
        if _face_idle_timer is not None:
            _face_idle_timer.cancel()
        _face_idle_timer = threading.Timer(_FACE_IDLE_DEBOUNCE, _flush_idle)
        _face_idle_timer.daemon = True
        _face_idle_timer.start()


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_END.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def _chunk_to_float32(chunk):
    """Pull a float32 numpy array + sample rate out of an AudioChunk,
    regardless of which attributes this piper-tts version exposes."""
    sr = getattr(chunk, "sample_rate", 22050)

    if hasattr(chunk, "audio_float_array"):
        data = np.asarray(chunk.audio_float_array, dtype="float32")
    elif hasattr(chunk, "audio_int16_array"):
        data = chunk.audio_int16_array.astype("float32") / 32768.0
    elif hasattr(chunk, "audio_int16_bytes"):
        data = np.frombuffer(chunk.audio_int16_bytes, dtype="int16").astype("float32") / 32768.0
    else:
        raise AttributeError(f"Unrecognized AudioChunk type: {type(chunk)}")

    return data, sr


class TTSBridge:
    """
    Thread-safe TTS bridge between an LLM and a speaker.
    Loads the Piper voice once and keeps it in memory.
    """

    def __init__(
        self,
        model_path: str = PIPER_MODEL,
        config_path: str = PIPER_CONFIG,
        length_scale: float = PIPER_LENGTH_SCALE,
        sentence_pause: float = PIPER_SENTENCE_PAUSE,
        device: int | None = None,
    ):
        self.length_scale   = length_scale
        self.sentence_pause = sentence_pause
        self.device         = device
        self._buffer        = ""

        print("Loading voice model…")
        self.voice = PiperVoice.load(model_path, config_path=config_path, use_cuda=False)
        print("Voice ready.")

    # ── Public API ────────────────────────────────────────────────────────────

    def speak(self, text: str):
        """Speak a complete block of text, broken into sentences."""
        _set_speaking()
        try:
            for sentence in _split_sentences(text):
                self._play(sentence)
        finally:
            _set_idle_soon()

    def stream_token(self, token: str):
        """
        Feed one token at a time (e.g. from an LLM streaming API).
        Speaks each sentence as soon as it's complete.
        Call flush() after the stream ends.
        """
        self._buffer += token
        while True:
            match = re.search(r'[.!?]\s', self._buffer)
            if not match:
                break
            end      = match.end()
            sentence = self._buffer[:end].strip()
            self._buffer = self._buffer[end:]
            if sentence:
                _set_speaking()
                try:
                    self._play(sentence)
                finally:
                    _set_idle_soon()

    def flush(self):
        """Speak any text remaining in the streaming buffer."""
        if self._buffer.strip():
            _set_speaking()
            try:
                self._play(self._buffer.strip())
            finally:
                _set_idle_soon()
            self._buffer = ""

    # ── Internal ──────────────────────────────────────────────────────────────

    def _synthesize(self, text: str) -> tuple:
        kwargs = {}
        if _HAS_SYN_CONFIG:
            kwargs["syn_config"] = SynthesisConfig(length_scale=self.length_scale)

        chunks = []
        sample_rate = self.voice.config.sample_rate
        for chunk in self.voice.synthesize(text, **kwargs):
            data, sample_rate = _chunk_to_float32(chunk)
            chunks.append(data)

        if not chunks:
            return np.zeros(0, dtype="float32"), sample_rate

        return np.concatenate(chunks), sample_rate

    def _play(self, text: str):
        data, sr = self._synthesize(text)
        if data.size == 0:
            return
        sd.play(data, samplerate=sr, device=self.device)
        sd.wait()
        time.sleep(self.sentence_pause)


# ── Module-level convenience functions ────────────────────────────────────────

_default_bridge: TTSBridge | None = None


def init(**kwargs):
    """Initialize the global TTSBridge (call once at app startup)."""
    global _default_bridge
    _default_bridge = TTSBridge(**kwargs)


def speak(text: str):
    """Speak text using the global bridge. Call init() first."""
    if _default_bridge is None:
        raise RuntimeError("Call llm_tts_bridge.init() before speak()")
    _default_bridge.speak(text)


if __name__ == "__main__":
    bridge = TTSBridge()
    bridge.speak("Good morning! I hope you are feeling well today.")
    print("Demo complete.")
