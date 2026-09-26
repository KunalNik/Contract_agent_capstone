"""Helpers for calling async code from synchronous code safely."""
import asyncio
import concurrent.futures
import contextvars
from typing import Any, Coroutine


def run_coro_sync(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine to completion from synchronous code.

    ``asyncio.run`` raises "cannot be called from a running event loop" when
    the caller is itself inside an event loop (e.g. a sync helper invoked from
    a FastAPI handler). In that case the coroutine runs on a short-lived worker
    thread with its own loop, preserving context variables (tenant, request id).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    ctx = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(ctx.run, asyncio.run, coro).result()
