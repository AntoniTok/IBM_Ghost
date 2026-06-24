#!/usr/bin/env python3
"""
test_speak.py — Minimal interactive TTS tester for piper-tts 1.x

Type something, press Enter, and hear it spoken back.
Type 'quit' (or Ctrl+C) to exit.

Run from the same folder as config.py:
    python test_speak.py
"""

import time

import numpy as np
import sounddevice as sd
from piper.voice import PiperVoice

try:
    from piper.voice import SynthesisConfig
    _HAS_SYN_CONFIG = True
except ImportError:
    _HAS_SYN_CONFIG = False

from config import PIPER_MODEL, PIPER_CONFIG, PIPER_LENGTH_SCALE, PIPER_SENTENCE_PAUSE


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


def speak(voice: PiperVoice, text: str):
    text = text.strip()
    if not text:
        return

    kwargs = {}
    if _HAS_SYN_CONFIG:
        kwargs["syn_config"] = SynthesisConfig(length_scale=PIPER_LENGTH_SCALE)

    chunks = []
    sample_rate = voice.config.sample_rate
    for chunk in voice.synthesize(text, **kwargs):
        data, sample_rate = _chunk_to_float32(chunk)
        chunks.append(data)

    if not chunks:
        print("  (no audio generated)")
        return

    audio = np.concatenate(chunks)
    sd.play(audio, samplerate=sample_rate)
    sd.wait()
    time.sleep(PIPER_SENTENCE_PAUSE)


def main():
    print("Loading voice model… (may take a few seconds)")
    voice = PiperVoice.load(PIPER_MODEL, config_path=PIPER_CONFIG, use_cuda=False)
    print("Voice ready! Type something and press Enter to hear it spoken.")
    print("Type 'quit' to exit.\n")

    while True:
        try:
            text = input("> ")
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if text.strip().lower() in ("quit", "exit"):
            print("Bye!")
            break

        speak(voice, text)


if __name__ == "__main__":
    main()
