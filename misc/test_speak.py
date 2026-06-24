#!/usr/bin/env python3
"""
test_speak.py — Minimal interactive TTS tester using Piper.

Type something, press Enter, and hear it spoken back.
Type 'quit' (or Ctrl+C) to exit.

Run from the same folder as config.py:
    python test_speak.py
"""

import io
import time

import sounddevice as sd
import soundfile as sf
from piper.voice import PiperVoice

from config import PIPER_MODEL, PIPER_CONFIG, PIPER_LENGTH_SCALE, PIPER_SENTENCE_PAUSE


def speak(voice: PiperVoice, text: str):
    text = text.strip()
    if not text:
        return

    buf = io.BytesIO()
    with sf.SoundFile(buf, mode="w", samplerate=22050, channels=1, format="WAV") as f:
        try:
            # Older piper-tts versions accept length_scale here
            voice.synthesize(text, f, length_scale=PIPER_LENGTH_SCALE)
        except TypeError:
            # Newer piper-tts versions set it on voice.config instead
            voice.config.length_scale = PIPER_LENGTH_SCALE
            voice.synthesize(text, f)

    buf.seek(0)
    data, samplerate = sf.read(buf, dtype="float32")
    sd.play(data, samplerate=samplerate)
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
