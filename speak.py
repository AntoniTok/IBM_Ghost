#!/usr/bin/env python3
"""
speak.py — Natural text-to-speech using Piper TTS for Raspberry Pi 4B.
Designed for calm, clear speech suitable for elderly users.

Usage:
    echo "Hello, how are you today?" | python speak.py
    python speak.py --text "Hello there"
    python speak.py                      # streaming stdin mode
    python speak.py --device 1           # use specific audio device index
    python speak.py --list-devices       # show available audio devices
"""

import sys
import argparse
import re
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

# Allow CLI to override speed
LENGTH_SCALE   = PIPER_LENGTH_SCALE
SENTENCE_PAUSE = PIPER_SENTENCE_PAUSE


def load_voice() -> PiperVoice:
    print("Loading voice model…", file=sys.stderr)
    voice = PiperVoice.load(PIPER_MODEL, config_path=PIPER_CONFIG, use_cuda=False)
    print("Voice ready.", file=sys.stderr)
    return voice


def split_sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
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


def synthesize_and_play(voice: PiperVoice, text: str, device: int | None = None):
    text = text.strip()
    if not text:
        return

    kwargs = {}
    if _HAS_SYN_CONFIG:
        kwargs["syn_config"] = SynthesisConfig(length_scale=LENGTH_SCALE)

    chunks = []
    sample_rate = voice.config.sample_rate
    for chunk in voice.synthesize(text, **kwargs):
        data, sample_rate = _chunk_to_float32(chunk)
        chunks.append(data)

    if not chunks:
        return

    audio = np.concatenate(chunks)
    sd.play(audio, samplerate=sample_rate, device=device)
    sd.wait()
    time.sleep(SENTENCE_PAUSE)


def speak(voice: PiperVoice, text: str, device: int | None = None):
    for sentence in split_sentences(text):
        synthesize_and_play(voice, sentence, device=device)


def main():
    parser = argparse.ArgumentParser(description="Natural TTS for Raspberry Pi using Piper")
    parser.add_argument("--text", "-t", help="Text to speak (or pipe via stdin)")
    parser.add_argument("--device", "-d", type=int, default=None,
                        help="Audio output device index (see --list-devices)")
    parser.add_argument("--list-devices", action="store_true",
                        help="List available audio devices and exit")
    parser.add_argument("--speed", type=float, default=LENGTH_SCALE,
                        help=f"Speech speed scale (default {LENGTH_SCALE}; higher = slower)")
    args = parser.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        sys.exit(0)

    global LENGTH_SCALE
    LENGTH_SCALE = args.speed

    voice = load_voice()

    if args.text:
        speak(voice, args.text, device=args.device)
    else:
        for line in sys.stdin:
            speak(voice, line, device=args.device)


if __name__ == "__main__":
    main()
