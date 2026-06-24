"""
latency_debug.py
=================
Lightweight timing + memory-snapshot helpers for tracking down latency
in the Granite Ghost pipeline.

Drop this file next to config.py (same directory as main.py, llm_pipeline.py,
llm_tools.py, service_manager.py) and import what you need:

    from latency_debug import Timer, log_mem, mem_snapshot

Overhead is negligible — each call just reads /proc/meminfo, no extra deps.

This is meant to be temporary debugging scaffolding. Once you've found the
bottleneck, feel free to delete this file and remove the imports/with-blocks
that reference it.
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger("latency")


def mem_snapshot() -> str:
    """
    Return a short string with available RAM and swap usage in MB,
    read straight from /proc/meminfo (works on any Linux, no deps).
    """
    try:
        info = {}
        with open("/proc/meminfo") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                info[key.strip()] = int(rest.strip().split()[0])  # value is in kB

        mem_avail  = info.get("MemAvailable", 0) // 1024
        mem_total  = info.get("MemTotal", 0) // 1024
        swap_total = info.get("SwapTotal", 0) // 1024
        swap_free  = info.get("SwapFree", 0) // 1024
        swap_used  = swap_total - swap_free

        return f"mem_avail={mem_avail}/{mem_total}MB swap_used={swap_used}/{swap_total}MB"
    except Exception as exc:
        return f"mem_snapshot_unavailable ({exc})"


def log_mem(label: str) -> None:
    """Log a one-line memory snapshot with a label."""
    log.info(f"[mem]    {label:<28} | {mem_snapshot()}")


class Timer:
    """
    Context manager that logs start/end + elapsed time + a memory
    snapshot for a labeled step.

        with Timer("pass1_llm_call"):
            do_the_thing()

    Produces two log lines:
        [timing] pass1_llm_call          START |        | mem_avail=...
        [timing] pass1_llm_call          END   |   1.23s | mem_avail=...
    """

    def __init__(self, label: str):
        self.label = label
        self.start = 0.0

    def __enter__(self):
        self.start = time.monotonic()
        log.info(f"[timing] {self.label:<28} START |        | {mem_snapshot()}")
        return self

    def __exit__(self, exc_type, exc, tb):
        elapsed = time.monotonic() - self.start
        status = "ERROR" if exc_type else "END  "
        log.info(f"[timing] {self.label:<28} {status} | {elapsed:6.2f}s | {mem_snapshot()}")
        return False  # never suppress exceptions
