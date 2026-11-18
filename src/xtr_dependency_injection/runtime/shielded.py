"""Work that must finish once begun — a teardown, a release — whatever cancels the caller."""

from __future__ import annotations

import asyncio
import contextvars
from typing import TYPE_CHECKING

from xtr_dependency_injection._text import safe_repr

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Never

__all__ = ["shielded"]


async def shielded[T](coro: Coroutine[object, Never, T], *, timeout: float) -> T:  # noqa: ASYNC109 — the deadline bounds the work itself; a caller's timeout would only cancel the wait, which this outlasts
    """Run ``coro`` to its end, whatever cancels the caller meanwhile, within ``timeout`` seconds.

    Closing what a unit of work opened is not optional: cancelled halfway, a
    session stays checked out of its pool and a file stays open. So ``coro``
    runs in a task of its own, in a copy of the caller's context, and a
    cancellation of the caller — however often it is repeated, as a cancel
    scope repeats it until it is honoured — only waits for it to finish.
    Then the caller is cancelled after all: the very cancellation it
    received is raised again, so whatever cancelled it recognises its own,
    with a note for whatever ``coro`` raised meanwhile, so nothing is lost.

    The deadline keeps a ``coro`` that never returns from holding the caller
    forever: it is cancelled once ``timeout`` has passed.

    Args:
        coro: The work to finish.
        timeout: How many seconds it is given.

    Returns:
        What ``coro`` returned.

    Raises:
        TimeoutError: If ``coro`` did not finish within ``timeout`` — or
            raised one itself.
        asyncio.CancelledError: If the caller was cancelled while ``coro``
            ran; raised once it finished.
        Exception: Whatever ``coro`` raised, when the caller was not cancelled.
    """
    task = asyncio.get_running_loop().create_task(
        asyncio.wait_for(coro, timeout), context=contextvars.copy_context()
    )
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            # Waiting is what a cancellation interrupts; the task goes on.
            _ = await asyncio.wait((task,))
        except asyncio.CancelledError as error:
            if cancellation is None:
                cancellation = error
    if cancellation is not None:
        failure = None if task.cancelled() else task.exception()
        if failure is not None:
            failures = failure.exceptions if isinstance(failure, BaseExceptionGroup) else (failure,)
            for raised in failures:
                cancellation.add_note(f"raised while finishing: {safe_repr(raised)}")
        raise cancellation
    return task.result()
