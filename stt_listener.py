#!/usr/bin/env python3
"""
stt_listener.py
---------------
Vosk-based speech-to-text listener for Raspberry Pi 4.
Triggered by wake word ("hey nova" etc.) OR GPIO sensor — whichever fires first.

Once triggered, records until silence, then calls on_utterance() with the
full transcript string. on_utterance() is patched by main.py to route into
the LLM pipeline.
"""

import os
import json
import logging
import queue
import re
import time
import threading
import pyaudio
from vosk import Model, KaldiRecognizer

from config import (
    VOSK_MODEL_PATH,
    WAKE_WORDS,
    SENSOR_GPIO_PIN,
    GPIO_BOUNCETIME_MS,
    STT_SAMPLE_RATE,
    STT_CHUNK,
    STT_SILENCE_TIMEOUT,
    STT_MAX_RECORD_SECS,
    STT_MIN_UTTERANCE_SECS,
)

log = logging.getLogger("stt_listener")

# ─── PIR event logging ────────────────────────────────────────────────────────
#
# Every PIR rising edge writes a row to the events table so the scheduler's
# update_routine_baseline() has real sensor data to learn from.

def _log_pir_event():
    """Write a PIR motion event to ghost.db. Non-blocking, fire-and-forget."""
    try:
        from db import get_db
        conn = get_db()
        conn.execute(
            "INSERT INTO events (source, payload) VALUES ('pir', '{}')"
        )
        conn.commit()
        conn.close()
    except Exception:
        log.debug("PIR event log failed (non-critical)", exc_info=True)

# ─── GPIO (optional) ──────────────────────────────────────────────────────────

_gpio_available = False
if SENSOR_GPIO_PIN is not None:
    try:
        import RPi.GPIO as GPIO
        _gpio_available = True
    except ImportError:
        print("[STT] RPi.GPIO not available — GPIO trigger disabled.")

# ─── Audio queue ──────────────────────────────────────────────────────────────

audio_queue: queue.Queue = queue.Queue()


def _audio_callback(in_data, frame_count, time_info, status):
    audio_queue.put(in_data)
    return (None, pyaudio.paContinue)


def open_mic_stream(pa: pyaudio.PyAudio) -> pyaudio.Stream:
    return pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=STT_SAMPLE_RATE,
        input=True,
        frames_per_buffer=STT_CHUNK,
        stream_callback=_audio_callback,
    )

# ─── Wake word detection ──────────────────────────────────────────────────────

_WAKE_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in WAKE_WORDS) + r")\b",
    re.IGNORECASE,
)

def _contains_wake_word(text: str) -> bool:
    return bool(_WAKE_RE.search(text or ""))


def listen_for_wake_word(rec: KaldiRecognizer) -> bool:
    while not audio_queue.empty():
        data = audio_queue.get()
        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result()).get("text", "")
            if _contains_wake_word(result):
                return True
        else:
            partial = json.loads(rec.PartialResult()).get("partial", "")
            if _contains_wake_word(partial):
                return True
    return False

# ─── Utterance recording ──────────────────────────────────────────────────────

def record_utterance(rec: KaldiRecognizer) -> str:
    """Record until silence or max time. Returns transcribed string."""
    while not audio_queue.empty():
        audio_queue.get()

    rec.Reset()

    transcript_parts  = []
    last_speech_time  = time.time()
    start_time        = time.time()
    got_speech        = False

    print("[STT] Listening for utterance…")

    while True:
        elapsed = time.time() - start_time
        if elapsed > STT_MAX_RECORD_SECS:
            print("[STT] Max record time reached.")
            break

        try:
            data = audio_queue.get(timeout=0.3)
        except queue.Empty:
            continue

        if rec.AcceptWaveform(data):
            result_text = json.loads(rec.Result()).get("text", "").strip()
            if result_text:
                print(f"[STT] Segment: '{result_text}'")
                transcript_parts.append(result_text)
                last_speech_time = time.time()
                got_speech = True
        else:
            partial = json.loads(rec.PartialResult()).get("partial", "").strip()
            if partial:
                last_speech_time = time.time()
                got_speech = True

        silence_duration = time.time() - last_speech_time
        if got_speech and silence_duration >= STT_SILENCE_TIMEOUT:
            print(f"[STT] Silence ({silence_duration:.1f}s), ending.")
            break

    final = json.loads(rec.FinalResult()).get("text", "").strip()
    if final:
        transcript_parts.append(final)

    utterance = " ".join(transcript_parts).strip()
    duration  = time.time() - start_time

    if duration < STT_MIN_UTTERANCE_SECS or not utterance:
        return ""

    return utterance

# ─── GPIO sensor trigger (polling — more reliable than event detection on Pi) ──

_sensor_triggered = threading.Event()
_gpio_poll_thread = None
_gpio_running     = False


def _gpio_poll_loop():
    """Poll the PIR pin in a thread instead of using event detection."""
    global _gpio_running
    last_state = 0
    debounce_ms = GPIO_BOUNCETIME_MS / 1000.0
    last_trigger_time = 0

    while _gpio_running:
        state = GPIO.input(SENSOR_GPIO_PIN)
        now   = time.time()

        if state == 1 and last_state == 0:
            # Rising edge detected — check debounce
            if (now - last_trigger_time) >= debounce_ms:
                print(f"[GPIO] Sensor trigger on pin {SENSOR_GPIO_PIN}")
                _sensor_triggered.set()
                _log_pir_event()
                last_trigger_time = now

        last_state = state
        time.sleep(0.05)   # poll every 50ms — fast enough for PIR


def setup_gpio():
    global _gpio_poll_thread, _gpio_running
    if not _gpio_available or SENSOR_GPIO_PIN is None:
        return
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(SENSOR_GPIO_PIN, GPIO.IN)
    _gpio_running     = True
    _gpio_poll_thread = threading.Thread(target=_gpio_poll_loop, daemon=True)
    _gpio_poll_thread.start()
    print(f"[GPIO] Sensor polling active on BCM pin {SENSOR_GPIO_PIN}")


def cleanup_gpio():
    global _gpio_running
    if _gpio_available and SENSOR_GPIO_PIN is not None:
        _gpio_running = False
        GPIO.cleanup()

# ─── Utterance handler (patched by main.py) ───────────────────────────────────

def on_utterance(text: str):
    """
    Default handler — replaced at runtime by main.py with the LLM pipeline.
    """
    print(f"\n[UTTERANCE] {text}\n")

# ─── Main loop ────────────────────────────────────────────────────────────────

def run():
    if not os.path.exists(VOSK_MODEL_PATH):
        raise FileNotFoundError(
            f"Vosk model not found at '{VOSK_MODEL_PATH}'.\n"
            "Download: https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip\n"
            "Extract to ./models/"
        )

    print(f"[STT] Loading model from {VOSK_MODEL_PATH} …")
    model = Model(VOSK_MODEL_PATH)
    rec   = KaldiRecognizer(model, STT_SAMPLE_RATE)
    rec.SetWords(False)

    pa     = pyaudio.PyAudio()
    stream = open_mic_stream(pa)

    setup_gpio()

    print(f"[STT] Ready. Wake words: {WAKE_WORDS}")
    if SENSOR_GPIO_PIN and _gpio_available:
        print(f"[STT] GPIO trigger active on pin {SENSOR_GPIO_PIN}")
    print("[STT] Waiting for trigger…\n")

    try:
        while True:
            triggered = False

            if _sensor_triggered.is_set():
                _sensor_triggered.clear()
                print("[STT] Triggered by sensor.")
                triggered = True

            if not triggered:
                triggered = listen_for_wake_word(rec)
                if triggered:
                    print("[STT] Wake word detected.")

            if triggered:
                time.sleep(0.15)   # let wake word audio drain
                utterance = record_utterance(rec)
                if utterance:
                    on_utterance(utterance)
                else:
                    print("[STT] No utterance detected, resuming watch.")

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n[STT] Shutting down.")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
        cleanup_gpio()


if __name__ == "__main__":
    run()
