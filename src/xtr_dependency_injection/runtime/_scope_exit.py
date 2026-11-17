"""Opening a unit's scope, and closing it whatever the unit is left with.

Every unit of work — :func:`~xtr_dependency_injection.unit_of_work`, a call
:func:`~xtr_dependency_injection.bind_callable` gives a scope of its own, a
served request — opens its scope here, so each closes it the same way.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Final

from wireup.errors import ContainerCloseError

from xtr_dependency_injection._text import safe_repr
from xtr_dependency_injection.exception import ScopeTeardownTimeoutError

from .shielded import shielded

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from wireup import AsyncContainer, ScopedAsyncContainer

__all__ = ["closing_scope"]

_TEARDOWN_TIMEOUT: Final[float] = 30.0
"""How many seconds a unit's scoped services are given to close."""

_LOGGER: Final = logging.getLogger("xtr_dependency_injection")
"""Where a failed teardown is recorded, once, whatever becomes of its error.

A note on the unit's error reaches only whoever reports that error — the
server's own output for a request — and an application log written while the
unit was still open never sees it; a failure raised after a clean unit
reaches no application code at all.
"""


@asynccontextmanager
async def closing_scope(engine: AsyncContainer) -> AsyncGenerator[ScopedAsyncContainer]:
    """Open a scope of ``engine`` for the block, and close every service it built afterwards.

    Closing is shielded: a cancellation arriving meanwhile — once, or again
    and again as a cancel scope delivers it — waits for every service's
    teardown, then is raised again; none is skipped. It is bounded: a
    teardown that never returns raises :class:`ScopeTeardownTimeoutError`.
    A teardown that fails or runs out of time while the block raised leaves
    the block's exception standing — a cancellation stays a cancellation —
    with a note naming what went wrong; without one, it is raised. The
    scope's instances are released as soon as it is
    closed, rather than whenever the garbage collector finds the cycle the
    scope keeps with them.
    Either way, a teardown that fails or runs out of time is also logged,
    once, as a warning on the ``xtr_dependency_injection`` logger.

    A scoped service's teardown — the code after ``yield`` in its factory —
    runs in a copy of the unit's context, in a task of its own. So it must
    not reset a context variable token set outside the teardown, a value it
    sets reaches nobody, and it must not hold an ``asyncio.timeout()``, an
    ``asyncio.TaskGroup`` or any other cancel scope open across its
    ``yield``. State kept per unit in the context belongs to a unit
    participant — see ``UnitParticipantInterface`` — not to a teardown.

    Raises:
        ScopeTeardownTimeoutError: If the teardown did not finish in time,
            and the block raised nothing.
        ExceptionGroup: Of what the teardown raised, when it failed and the
            block raised nothing.
        asyncio.CancelledError: If the block was cancelled while closing;
            what the teardown raised meanwhile is a note on it.
    """
    scope = engine.enter_scope()
    _ = await scope.__aenter__()
    try:
        yield scope
    except BaseException as error:
        await _close(scope, error)
        raise
    await _close(scope, None)


async def _close(scope: ScopedAsyncContainer, error: BaseException | None) -> None:
    """Close ``scope``, unwinding ``error`` through its services when the block raised one."""
    try:
        await shielded(
            _exit_logging_failures(scope, error),
            timeout=_TEARDOWN_TIMEOUT,
        )
    except TimeoutError as timeout:
        _LOGGER.warning(
            "Closing a unit's services did not finish within %s seconds.", _TEARDOWN_TIMEOUT
        )
        if error is None:
            raise ScopeTeardownTimeoutError(_TEARDOWN_TIMEOUT) from timeout
        error.add_note(
            f"closing the unit's services did not finish within {_TEARDOWN_TIMEOUT} seconds"
        )
    except ContainerCloseError as failed:
        if error is None:
            # A plain group, as for every other multi-failure: no caller catches a wireup type.
            raise ExceptionGroup(
                "closing the unit's services failed", list(failed.exceptions)
            ) from None
        for failure in failed.exceptions:
            error.add_note(f"closing the unit's services also failed: {safe_repr(failure)}")
    finally:
        objects = scope._current_scope_objects  # noqa: SLF001 — wireup keeps the scope in its own object map; clearing it releases scoped instances without waiting for cyclic GC  # pyright: ignore[reportPrivateUsage]
        if objects is not None:
            objects.clear()


async def _exit_logging_failures(scope: ScopedAsyncContainer, error: BaseException | None) -> None:
    """Exit ``scope``, logging what its services' teardown raised before it travels on.

    Logged here, inside the shielded teardown, so a failure is recorded once
    whether it then becomes a note on the unit's error, a note on a
    cancellation, or the error raised.
    """
    try:
        await scope.__aexit__(
            None if error is None else type(error),
            error,
            None if error is None else error.__traceback__,
        )
    except ContainerCloseError as failed:
        _LOGGER.warning(
            "Closing a unit's services failed: %s",
            "; ".join(safe_repr(failure) for failure in failed.exceptions),
        )
        raise
