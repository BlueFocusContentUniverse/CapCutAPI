#!/usr/bin/env python3
"""Opt-in memory growth diagnostics.

This module provides a lightweight background task that periodically logs
`tracemalloc` allocation diffs. It is intended to help diagnose gradual memory
growth ("MB/hour") in long-running FastAPI/Uvicorn processes.

Enable via env:
- MEMORY_DEBUG=1 (or true/yes/on)
Optional tuning:
- MEMORY_DEBUG_INTERVAL_SECONDS=60
- MEMORY_DEBUG_TOP_N=20
- MEMORY_DEBUG_NFRAMES=25

Notes:
- `tracemalloc` tracks Python allocations (not native allocations in C libs).
- RSS logging is best-effort (uses `psutil` if installed).
"""

from __future__ import annotations

import asyncio
import gc
import logging
import os
import tracemalloc
from typing import Optional


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_rss_bytes_best_effort() -> Optional[int]:
    """Return process RSS in bytes if available, else None."""
    try:
        import psutil  # type: ignore

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except Exception:
        return None


def memory_debug_enabled() -> bool:
    return _env_flag("MEMORY_DEBUG", default=False)


async def memory_debug_loop(
    *,
    logger: logging.Logger,
    interval_seconds: int = 60,
    top_n: int = 20,
    nframes: int = 25,
) -> None:
    """Periodically log allocation diffs.

    This loop is designed to be cancellable via task cancellation.
    """
    interval_seconds = max(5, int(interval_seconds))
    top_n = max(5, int(top_n))
    nframes = max(1, int(nframes))

    if not tracemalloc.is_tracing():
        tracemalloc.start(nframes)

    prev = tracemalloc.take_snapshot()
    logger.warning(
        "MEMORY_DEBUG enabled: interval=%ss top_n=%s nframes=%s",
        interval_seconds,
        top_n,
        nframes,
    )

    try:
        while True:
            await asyncio.sleep(interval_seconds)

            # Encourage cyclic GC so we can distinguish true retention
            # from delayed collection.
            try:
                gc.collect()
            except Exception:
                pass

            current, peak = tracemalloc.get_traced_memory()
            rss = _get_rss_bytes_best_effort()
            rss_mb = f"{rss / (1024 * 1024):.1f}MB" if rss is not None else "n/a"

            snap = tracemalloc.take_snapshot()
            stats = snap.compare_to(prev, "lineno")
            prev = snap

            header = (
                f"MEMORY_DEBUG tick: traced_current={current / (1024 * 1024):.1f}MB "
                f"traced_peak={peak / (1024 * 1024):.1f}MB rss={rss_mb}"
            )
            logger.warning(header)

            if not stats:
                logger.warning("MEMORY_DEBUG: no diff stats")
                continue

            # Only log positive growth lines to reduce noise.
            growth = [s for s in stats if s.size_diff > 0]
            if not growth:
                logger.warning(
                    "MEMORY_DEBUG: no positive allocation growth in interval"
                )
                continue

            for idx, stat in enumerate(growth[:top_n], start=1):
                frame = stat.traceback[0]
                logger.warning(
                    "MEMORY_DEBUG #%02d: +%.1fKB (%+d) at %s:%d | %s",
                    idx,
                    stat.size_diff / 1024.0,
                    stat.count_diff,
                    frame.filename,
                    frame.lineno,
                    (frame.line or "").strip(),
                )

    except asyncio.CancelledError:
        logger.warning("MEMORY_DEBUG task cancelled")
        raise


def start_memory_debug_task(logger: logging.Logger) -> Optional[asyncio.Task]:
    """Start the background memory debug task if enabled.

    Returns the created task or None if disabled.
    """
    if not memory_debug_enabled():
        return None

    interval = _env_int("MEMORY_DEBUG_INTERVAL_SECONDS", 60)
    top_n = _env_int("MEMORY_DEBUG_TOP_N", 20)
    nframes = _env_int("MEMORY_DEBUG_NFRAMES", 25)

    return asyncio.create_task(
        memory_debug_loop(
            logger=logger,
            interval_seconds=interval,
            top_n=top_n,
            nframes=nframes,
        )
    )
