"""Cooperative SIGTERM for the two standalone asyncio dispatchers."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable


async def run_with_shutdown(service: Callable[[], Awaitable[None]]) -> None:
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("dispatcher shutdown requires a running task")
    previous = signal.getsignal(signal.SIGTERM)
    if previous is None:
        raise RuntimeError("dispatcher cannot preserve the existing SIGTERM handler")
    requested = False

    def request_shutdown() -> None:
        nonlocal requested
        if not requested:
            requested = True
            task.cancel()

    loop.add_signal_handler(signal.SIGTERM, request_shutdown)
    try:
        await service()
    except asyncio.CancelledError:
        if not requested:
            raise
    finally:
        # A second SIGTERM must not interrupt engine/checkpointer cleanup.
        loop.remove_signal_handler(signal.SIGTERM)
        signal.signal(signal.SIGTERM, previous)
