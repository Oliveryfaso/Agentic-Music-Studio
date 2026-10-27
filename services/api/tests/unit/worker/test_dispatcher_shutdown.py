"""Real entrypoint signals with synthetic DB/broker boundaries; no live services."""

from __future__ import annotations

import asyncio
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

CHILD = r"""
import asyncio
import importlib
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from motif_forge import config

settings = config.Settings.for_test(
    postgres_dsn="postgresql+psycopg://synthetic@127.0.0.1:1/synthetic",
    redis_url="redis://127.0.0.1:1/0",
    artifact_root="artifacts", temp_root="tmp", outbox_batch_size=1,
)
config.get_settings = lambda: settings
role = sys.argv[1]
module = importlib.import_module("motif_forge.worker." + role)

def emit(value):
    print(value, flush=True)

class Engine:
    async def dispose(self):
        if len(sys.argv) > 2 and sys.argv[2] == "hold_cleanup":
            emit("cleanup_waiting")
            while not Path("second_sent").exists():
                await asyncio.sleep(0.01)
            # Cross an event-loop I/O cycle after the second OS signal.
            await asyncio.sleep(0.05)
            emit("cleanup_survived_repeat")
            while not Path("release_cleanup").exists():
                await asyncio.sleep(0.01)
        emit("disposed")

module.configure_langsmith = lambda *a, **k: None
module.create_postgres_engine = lambda *a, **k: Engine()
module.create_session_factory = lambda engine: lambda: None

if role == "dispatcher":
    from motif_forge.worker.outbox import OutboxMessage

    message = OutboxMessage(
        event_id=UUID("11111111-1111-4111-8111-111111111111"),
        topic="media.job.dispatch.requested", dedupe_key="synthetic-shutdown",
        payload={"job_id": "22222222-2222-4222-8222-222222222222"}, attempts=1,
    )

    class Store:
        async def claim_batch(self, **kwargs):
            emit("claimed")
            return (message,)

        async def mark_published(self, *args, **kwargs):
            emit("published")
            return True

        async def mark_failed(self, *args, **kwargs):
            emit("failed")
            return True

    class Publisher:
        async def publish(self, message):
            emit("ready")
            await asyncio.Future()

    module.PostgresOutboxStore = lambda *a, **k: Store()
    module.CeleryMediaJobPublisher = lambda *a, **k: Publisher()
else:
    @asynccontextmanager
    async def checkpointer(dsn):
        try:
            emit("ready")
            await asyncio.Future()
            yield None
        finally:
            emit("checkpointer_closed")

    module.postgres_checkpointer = checkpointer

module.main()
emit("returned")
"""


def _read_until(child: subprocess.Popen[bytes], wanted: str) -> list[str]:
    assert child.stdout is not None
    received = b""
    until = time.monotonic() + 15
    with selectors.DefaultSelector() as selector:
        selector.register(child.stdout, selectors.EVENT_READ)
        while time.monotonic() < until:
            if not selector.select(timeout=max(0, until - time.monotonic())):
                break
            chunk = os.read(child.stdout.fileno(), 4096)
            if not chunk:
                break
            received += chunk
            assert len(received) <= 65536
            lines = received.decode().splitlines()
            if wanted in lines:
                return lines
    pytest.fail(f"synthetic child did not reach {wanted}: {received!r}, exit={child.poll()}")


def _start(role: str, tmp_path: Path, *options: str) -> subprocess.Popen[bytes]:
    source = Path(__file__).resolve().parents[3] / "src"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(source),
        "PYTHONDONTWRITEBYTECODE": "1",
        "LANG": "C",
        "LC_ALL": "C",
    }
    return subprocess.Popen(
        [sys.executable, "-B", "-c", CHILD, role, *options],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _cleanup(child: subprocess.Popen[bytes]) -> None:
    if child.poll() is None:
        child.kill()  # This exact test-owned child only; never a service/container.
    child.communicate(timeout=5)


@pytest.mark.parametrize("role", ["dispatcher", "resume_dispatcher"])
@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_actual_entrypoint_signal_cleans_resources_and_returns_zero(
    role: str, signum: signal.Signals, tmp_path: Path
) -> None:
    child = _start(role, tmp_path)
    try:
        before = _read_until(child, "ready")
        child.send_signal(signum)
        stdout, stderr = child.communicate(timeout=10)
        lines = before + stdout.decode().splitlines()
        assert child.returncode == 0, (lines, stderr)
        assert lines.count("disposed") == 1
        assert lines[-1] == "returned"
        assert "published" not in lines and "failed" not in lines
        if role == "resume_dispatcher":
            assert lines.count("checkpointer_closed") == 1
        assert stderr == b""
    finally:
        _cleanup(child)


def test_repeated_sigterm_does_not_interrupt_real_dispatcher_cleanup(tmp_path: Path) -> None:
    child = _start("dispatcher", tmp_path, "hold_cleanup")
    try:
        lines = _read_until(child, "ready")
        child.send_signal(signal.SIGTERM)
        lines += _read_until(child, "cleanup_waiting")
        child.send_signal(signal.SIGTERM)
        (tmp_path / "second_sent").touch()
        lines += _read_until(child, "cleanup_survived_repeat")
        (tmp_path / "release_cleanup").touch()
        stdout, stderr = child.communicate(timeout=10)
        lines += stdout.decode().splitlines()
        assert child.returncode == 0, (lines, stderr)
        assert lines.count("disposed") == 1
        assert lines[-1] == "returned"
        assert "published" not in lines and "failed" not in lines
        assert stderr == b""
    finally:
        _cleanup(child)


@pytest.mark.asyncio
async def test_non_signal_cancellation_is_not_swallowed() -> None:
    from motif_forge.worker.shutdown import run_with_shutdown

    started = asyncio.Event()
    cleaned: list[bool] = []
    previous = signal.getsignal(signal.SIGTERM)

    async def service() -> None:
        try:
            started.set()
            await asyncio.Future()
        finally:
            cleaned.append(True)

    task = asyncio.create_task(run_with_shutdown(service))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned == [True]
    assert signal.getsignal(signal.SIGTERM) == previous


@pytest.mark.asyncio
async def test_service_error_propagates_and_prior_signal_handler_is_restored() -> None:
    from motif_forge.worker.shutdown import run_with_shutdown

    previous = signal.getsignal(signal.SIGTERM)

    async def service() -> None:
        raise ValueError("synthetic service failure")

    with pytest.raises(ValueError, match="synthetic service failure"):
        await run_with_shutdown(service)
    assert signal.getsignal(signal.SIGTERM) == previous
