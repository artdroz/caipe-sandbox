"""Terminal lifecycle and bounded I/O independent of management workers."""

import asyncio
import contextvars
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from fastapi import HTTPException
from starlette.websockets import WebSocketDisconnect


class TerminalIO:
    def __init__(self, workers):
        if type(workers) is not int or workers < 1:
            raise ValueError("PORTAL_TERMINAL_IO_WORKERS must be a positive integer")
        self.pool = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="portal-terminal"
        )
        self.slots = asyncio.Semaphore(workers)
        self.closed = False

    async def run(self, function, *args, **kwargs):
        if self.closed:
            raise HTTPException(503, "Terminal I/O is shutting down")
        await self.slots.acquire()
        try:
            if self.closed:
                raise HTTPException(503, "Terminal I/O is shutting down")
            context = contextvars.copy_context()
            future = asyncio.get_running_loop().run_in_executor(
                self.pool, context.run, partial(function, *args, **kwargs)
            )
        except BaseException:
            self.slots.release()
            raise

        def release(done):
            self.slots.release()
            if not done.cancelled():
                done.exception()

        # Cancellation cannot free capacity while a native call is still running.
        future.add_done_callback(release)
        return await asyncio.shield(future)

    def close(self):
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)


async def warn_restart(ws, remaining):
    await asyncio.wait_for(
        ws.send_bytes(
            json.dumps({"type": "draining", "seconds_remaining": remaining}).encode()
        ),
        timeout=1,
    )


class TerminalDrain:
    """Cancel attaching sessions immediately; active sessions get the drain window."""

    def __init__(self):
        self.active = False
        self.restarting = False

    async def watch(self, drain, ws, parent):
        warned = False
        while True:
            remaining = drain.remaining()
            if remaining is not None:
                if not warned:
                    warned = True
                    try:
                        await warn_restart(ws, remaining)
                    except (TimeoutError, RuntimeError, OSError, WebSocketDisconnect):
                        self.restarting = True
                        parent.cancel()
                        return
                if not self.active or remaining <= 0:
                    self.restarting = True
                    parent.cancel()
                    return
            await asyncio.sleep(0.25)


async def attach_exec(factory, timeout, *, run=asyncio.to_thread):
    cancelled = threading.Event()
    started = threading.Event()

    def attach():
        started.set()
        if not cancelled.is_set():
            return factory()

    task = asyncio.create_task(run(attach))

    def close_late(done):
        try:
            connection = done.result()
            if connection is not None:
                connection.close()
        except (Exception, asyncio.CancelledError):
            pass

    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout)
    except BaseException:
        cancelled.set()
        if not started.is_set():
            task.cancel()
        task.add_done_callback(close_late)
        raise
