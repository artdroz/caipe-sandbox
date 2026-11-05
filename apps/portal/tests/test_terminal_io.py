"""Native I/O cannot consume management workers or exceed its capacity on cancellation."""

import asyncio
import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from test_portal import SETTINGS

from portal.config import Settings
from portal.terminal import TerminalIO, attach_exec


def test_blocked_terminal_keeps_management_free_and_retains_capacity_on_cancel():
    async def run():
        asyncio.get_running_loop().set_default_executor(
            ThreadPoolExecutor(max_workers=1)
        )
        io = TerminalIO(1)
        entered, release, second_entered = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def blocked():
            entered.set()
            assert release.wait(3)
            raise OSError("Native connection closed")

        first = asyncio.create_task(io.run(blocked))
        second = None
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            second = asyncio.create_task(io.run(second_entered.set))
            assert (
                await asyncio.wait_for(asyncio.to_thread(lambda: "management"), 0.5)
                == "management"
            )
            await asyncio.sleep(0.02)
            assert not second_entered.is_set()
            release.set()
            await asyncio.wait_for(second, 1)
            assert second_entered.is_set()
        finally:
            release.set()
            if second:
                await asyncio.gather(second, return_exceptions=True)
            io.close()

    asyncio.run(run())


def test_waiting_attachment_does_not_execute_after_its_timeout():
    async def run():
        io = TerminalIO(1)
        entered, release = threading.Event(), threading.Event()
        factory = Mock()

        def blocked():
            entered.set()
            assert release.wait(3)

        busy = asyncio.create_task(io.run(blocked))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            with pytest.raises(TimeoutError):
                await attach_exec(factory, 0.02, run=io.run)
            release.set()
            await busy
            await io.run(lambda: None)
            factory.assert_not_called()
        finally:
            release.set()
            await asyncio.gather(busy, return_exceptions=True)
            io.close()

    asyncio.run(run())


def test_pool_transports_request_context_and_rejects_work_after_shutdown():
    async def run():
        io = TerminalIO(1)
        request = contextvars.ContextVar("request", default="missing")
        request.set("request-42")
        assert await io.run(request.get) == "request-42"
        entered, release = threading.Event(), threading.Event()

        def blocked():
            entered.set()
            assert release.wait(3)

        busy = asyncio.create_task(io.run(blocked))
        waiting = None
        native = Mock()
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            waiting = asyncio.create_task(io.run(native))
            await asyncio.sleep(0)
            io.close()
            release.set()
            await busy
            with pytest.raises(HTTPException) as rejected:
                await waiting
            assert rejected.value.status_code == 503
            native.assert_not_called()
            with pytest.raises(HTTPException):
                await io.run(native)
        finally:
            release.set()
            if waiting:
                await asyncio.gather(waiting, return_exceptions=True)
            io.close()

    asyncio.run(run())


@pytest.mark.parametrize("workers", [0, -1, True])
def test_pool_rejects_invalid_worker_limits(workers):
    with pytest.raises(ValueError, match="TERMINAL_IO_WORKERS"):
        TerminalIO(workers)


@pytest.mark.parametrize("value", ["0", "-1"])
def test_invalid_operator_worker_limit_is_rejected_at_configuration_load(
    monkeypatch, value
):
    monkeypatch.setenv("PORTAL_TERMINAL_IO_WORKERS", value)
    with pytest.raises(ValueError, match="TERMINAL_IO_WORKERS"):
        Settings.from_env()


def test_operator_can_select_the_worker_budget(monkeypatch):
    for name, value in SETTINGS.__dict__.items():
        monkeypatch.setenv("PORTAL_" + name.upper(), str(value))
    monkeypatch.setenv("PORTAL_TERMINAL_IO_WORKERS", "7")
    assert Settings.from_env().terminal_io_workers == 7
