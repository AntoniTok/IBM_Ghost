"""
service_manager.py
==================
Granite Ghost – Service Scheduler & LLM Interaction Endpoint

Two responsibilities:
  1. SCHEDULER  – runs passive services (weather, email, calendar, SMS) on a
                  morning + afternoon schedule and keeps JSON data files fresh.
  2. HTTP API   – a tiny FastAPI server the LLM pipeline calls to trigger any
                  service on-demand and to read the latest cached data.

Usage
-----
    # Install deps once:
    pip install fastapi uvicorn apscheduler requests

    # Start the server (runs scheduler + API together):
    python service_manager.py

    # Or run scheduler-only (no HTTP, good for cron fallback):
    python service_manager.py --scheduler-only

Endpoints
---------
    GET  /status              – health check + last-run timestamps
    POST /run/{service}       – trigger a service right now and wait for result
    GET  /data/{service}      – return the cached JSON for a service
    POST /spotify             – send a Spotify intent (body: {"intent": "play", "query": "..."})
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ─── Configuration (all values live in config.py) ───────────────────────────

from config import (
    BASE_DIR, DATA_DIR, LOG_FILE,
    MORNING_HOUR, MORNING_MINUTE, AFTERNOON_HOUR, AFTERNOON_MINUTE,
    BT_DEVICE_ADDRESS,
    WEATHER_OUTPUT, EMAIL_OUTPUT, CALENDAR_OUTPUT, SMS_OUTPUT,
    API_HOST, API_PORT,
)
from latency_debug import log_mem

# ─── Service registry ───────────────────────────────────────────────────────
#
# Each entry describes how to invoke a service and where it writes its output.
# "scheduled" = included in the morning/afternoon passive runs.
# Spotify is excluded from the schedule; it's always on-demand only.

SERVICES: dict[str, dict[str, Any]] = {
    "weather": {
        "script":    BASE_DIR / "weather_service.py",
        "output":    WEATHER_OUTPUT,
        "scheduled": True,
        "args":      [],
    },
    "email": {
        "script":    BASE_DIR / "email_service.py",
        "output":    EMAIL_OUTPUT,
        "scheduled": True,
        "args":      [],
    },
    "calendar": {
        "script":    BASE_DIR / "fetch_calendar.py",
        "output":    CALENDAR_OUTPUT,
        "scheduled": True,
        "args":      [],
    },
    "sms": {
        "script":    BASE_DIR / "sms_reader.py",
        "output":    SMS_OUTPUT,
        "scheduled": True,
        "args":      [],
    },
    # Spotify is NOT in the passive schedule; it is only triggered via /spotify
}

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE),
    ],
)
log = logging.getLogger("service_manager")

# ─── State ───────────────────────────────────────────────────────────────────

_last_run: dict[str, str]   = {}   # service -> ISO timestamp of last successful run
_last_error: dict[str, str] = {}   # service -> last error string
_run_lock = threading.Lock()       # prevent two runs of the same service in parallel

# Face state for the kiosk display. llm_tts_bridge.TTSBridge.speak() POSTs
# "speaking" before audio output and "idle" after; face.html polls the GET
# endpoint and toggles a CSS class on <body>. In-memory — resets to 'idle'
# on every restart, which is the correct default.
_VALID_FACE_STATES = {"idle", "speaking"}
_face_state: dict[str, str] = {"state": "idle"}
_face_lock = threading.Lock()

# Where face.html lives on disk (served by the /face route below).
FACE_HTML = BASE_DIR / "web-app" / "face.html"


# ─── Service runner ──────────────────────────────────────────────────────────

def run_service(name: str) -> dict[str, Any]:
    """
    Run a service script in a subprocess.
    Returns {"status": "success"|"error", "data": ..., "error": ...}
    """
    if name not in SERVICES:
        return {"status": "error", "error": f"Unknown service: {name}"}

    cfg = SERVICES[name]
    script: Path = cfg["script"]
    output: Path = cfg["output"]
    extra_args: list = cfg.get("args", [])

    if not script.exists():
        msg = f"Script not found: {script}"
        log.error(msg)
        _last_error[name] = msg
        return {"status": "error", "error": msg}

    with _run_lock:
        log.info(f"Running service: {name}")
        log_mem(f"before {name} subprocess")
        cmd = [sys.executable, str(script)] + [str(a) for a in extra_args]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(BASE_DIR),
            )
        except subprocess.TimeoutExpired:
            msg = f"{name} timed out after 60 s"
            log.error(msg)
            _last_error[name] = msg
            return {"status": "error", "error": msg}
        except Exception as exc:
            msg = f"{name} subprocess error: {exc}"
            log.error(msg)
            _last_error[name] = msg
            return {"status": "error", "error": msg}

        if result.returncode != 0:
            msg = result.stderr.strip() or f"exited {result.returncode}"
            log.error(f"{name} failed: {msg}")
            _last_error[name] = msg
            return {"status": "error", "error": msg}

        _last_run[name]  = datetime.utcnow().isoformat() + "Z"
        _last_error.pop(name, None)
        log.info(f"{name} completed successfully")
        log_mem(f"after {name} subprocess")

        # Read and return the output file
        return _read_data(name)


def _read_data(name: str) -> dict[str, Any]:
    """Read the cached JSON output for a service."""
    if name not in SERVICES:
        return {"status": "error", "error": f"Unknown service: {name}"}

    output: Path = SERVICES[name]["output"]
    if not output.exists():
        return {"status": "error", "error": f"No data yet for {name}. Run it first."}

    try:
        return json.loads(output.read_text())
    except Exception as exc:
        return {"status": "error", "error": f"Could not read {output}: {exc}"}


# ─── Scheduler ───────────────────────────────────────────────────────────────

def _run_all_scheduled() -> None:
    """Run every scheduled service. Called by both schedule slots."""
    log.info("Starting scheduled pass …")
    for name, cfg in SERVICES.items():
        if cfg.get("scheduled"):
            run_service(name)
    log.info("Scheduled pass complete.")


def start_scheduler() -> None:
    """
    Use APScheduler if available, otherwise fall back to a simple threading loop.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _run_all_scheduled, "cron",
            hour=MORNING_HOUR, minute=MORNING_MINUTE,
            id="morning_run",
        )
        scheduler.add_job(
            _run_all_scheduled, "cron",
            hour=AFTERNOON_HOUR, minute=AFTERNOON_MINUTE,
            id="afternoon_run",
        )
        scheduler.start()
        log.info(
            f"APScheduler running – morning {MORNING_HOUR:02d}:{MORNING_MINUTE:02d}, "
            f"afternoon {AFTERNOON_HOUR:02d}:{AFTERNOON_MINUTE:02d}"
        )
    except ImportError:
        log.warning("APScheduler not found – using built-in threading scheduler.")
        _start_simple_scheduler()


def _start_simple_scheduler() -> None:
    """Fallback scheduler that runs in a daemon thread."""

    def _loop():
        while True:
            now = datetime.now()
            is_morning   = (now.hour == MORNING_HOUR   and now.minute == MORNING_MINUTE)
            is_afternoon = (now.hour == AFTERNOON_HOUR and now.minute == AFTERNOON_MINUTE)
            if is_morning or is_afternoon:
                _run_all_scheduled()
                time.sleep(61)  # skip rest of this minute
            time.sleep(30)

    t = threading.Thread(target=_loop, daemon=True, name="scheduler")
    t.start()
    log.info("Simple scheduler thread started.")


# ─── Spotify handler (imported once, re-used) ────────────────────────────────

_spotify_handler = None
_spotify_lock = threading.Lock()


def get_spotify_handler():
    global _spotify_handler
    with _spotify_lock:
        if _spotify_handler is None:
            spec = importlib.util.spec_from_file_location(
                "spotify_handler", BASE_DIR / "spotify_handler.py"
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _spotify_handler = mod.SpotifyHandler()
        return _spotify_handler


# ─── FastAPI application ─────────────────────────────────────────────────────

def build_app():
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import JSONResponse, HTMLResponse
        from pydantic import BaseModel
    except ImportError:
        log.error("fastapi / uvicorn not installed. Run: pip install fastapi uvicorn")
        sys.exit(1)

    app = FastAPI(
        title="Granite Ghost Service Manager",
        description="Scheduler + LLM interaction endpoint for the Granite Ghost device.",
        version="1.0.0",
    )

    # ── Face kiosk — serves the SVG ghost page + the state it animates to ──
    #
    # The kiosk URL is http://localhost:8080/face. face.html polls
    # /api/face/state every ~200ms and grows/shrinks the SVG.
    # llm_tts_bridge.TTSBridge.speak() POSTs to /api/face/state with
    # {"state": "speaking"} or "idle".

    @app.get("/face", response_class=HTMLResponse)
    def face_kiosk():
        if not FACE_HTML.exists():
            raise HTTPException(404, f"face.html not found at {FACE_HTML}")
        return HTMLResponse(FACE_HTML.read_text())

    @app.get("/api/face/state")
    def get_face_state():
        with _face_lock:
            return dict(_face_state)

    @app.post("/api/face/state")
    def set_face_state(data: dict):
        state = data.get("state")
        if state not in _VALID_FACE_STATES:
            raise HTTPException(
                400, f"state must be one of {sorted(_VALID_FACE_STATES)}"
            )
        with _face_lock:
            _face_state["state"] = state
            return dict(_face_state)

    # ── GET /status ──────────────────────────────────────────────────────────

    @app.get("/status")
    def status():
        """Health check and last-run info for all services."""
        services_info = {}
        for name, cfg in SERVICES.items():
            output: Path = cfg["output"]
            services_info[name] = {
                "scheduled":    cfg.get("scheduled", False),
                "last_run":     _last_run.get(name),
                "last_error":   _last_error.get(name),
                "data_file":    str(output),
                "data_exists":  output.exists(),
                "data_age_sec": (
                    round(time.time() - output.stat().st_mtime)
                    if output.exists() else None
                ),
            }
        return {
            "status":      "ok",
            "server_time": datetime.utcnow().isoformat() + "Z",
            "services":    services_info,
        }

    # ── POST /run/{service} ──────────────────────────────────────────────────

    @app.post("/run/{service}")
    def run(service: str):
        """
        Trigger a service immediately and return the result.
        Useful when the LLM needs fresh data right now.
        """
        if service not in SERVICES:
            raise HTTPException(404, f"Unknown service '{service}'. "
                                     f"Valid: {list(SERVICES)}")

        def _run_bg():
            run_service(service)

        # Run in a thread so the HTTP request doesn't block forever on slow ops
        t = threading.Thread(target=_run_bg, daemon=True)
        t.start()
        t.join(timeout=65)  # wait up to 65 s

        return _read_data(service)

    # ── GET /data/{service} ──────────────────────────────────────────────────

    @app.get("/data/{service}")
    def data(service: str):
        """Return the most recently cached data for a service."""
        if service not in SERVICES:
            raise HTTPException(404, f"Unknown service '{service}'. "
                                     f"Valid: {list(SERVICES)}")
        return _read_data(service)

    # ── POST /spotify ────────────────────────────────────────────────────────

    class SpotifyRequest(BaseModel):
        intent: str
        query:  str = ""

    @app.post("/spotify")
    def spotify(req: SpotifyRequest):
        """
        Send a Spotify intent to the SpotifyHandler.
        Valid intents: play, pause, next, previous, volume, now_playing,
                       favourites, save, playlist, recent, similar,
                       queue, repeat, shuffle, restart
        Body example:  {"intent": "play", "query": "Fly Me to the Moon Sinatra"}
        """
        try:
            handler = get_spotify_handler()
        except Exception as exc:
            raise HTTPException(503, f"Spotify not available: {exc}")

        result = handler.handle_intent(req.intent, req.query)
        return result

    return app


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Granite Ghost Service Manager")
    parser.add_argument(
        "--scheduler-only", action="store_true",
        help="Run the scheduler without the HTTP API (good for testing cron fallback).",
    )
    parser.add_argument(
        "--host", default=API_HOST,
        help=f"API bind address (default {API_HOST})",
    )
    parser.add_argument(
        "--port", type=int, default=API_PORT,
        help=f"API port (default {API_PORT})",
    )
    parser.add_argument(
        "--run-now", metavar="SERVICE",
        help="Run a single service immediately and exit (useful for testing).",
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Quick one-shot run
    if args.run_now:
        result = run_service(args.run_now)
        print(json.dumps(result, indent=2))
        return

    # Scheduler-only mode
    if args.scheduler_only:
        start_scheduler()
        log.info("Scheduler-only mode. Press Ctrl+C to exit.")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            log.info("Shutting down.")
        return

    # Full mode: scheduler + API
    start_scheduler()

    try:
        import uvicorn
    except ImportError:
        log.error("uvicorn not installed. Run: pip install uvicorn")
        sys.exit(1)

    app = build_app()
    log.info(f"Starting API on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
