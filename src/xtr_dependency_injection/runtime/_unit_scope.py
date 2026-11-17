"""Where the unit of work open in this context is kept.

Kept apart from the public :mod:`~xtr_dependency_injection.runtime.unit_of_work`
so the engine glue — :func:`~xtr_dependency_injection.bind_callable` — can
read it without importing the container wrapper the public API hands out.
"""

from __future__ import annotations

import asyncio
import threading
import weakref
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from typing import TYPE_CHECKING, final

from wireup.errors import UnknownServiceRequestedError

from xtr_dependency_injection._text import safe_repr
from xtr_dependency_injection.exception import UnitReadDuringSingletonBuildError

from ._detached_variables import register_detached_variable

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence

    from wireup import AsyncContainer, ScopedAsyncContainer
    from xtr_service_contracts import UnitParticipantInterface

__all__ = [
    "Unit",
    "UnitParticipants",
    "building_singleton",
    "counted",
    "current_unit_record",
    "entered",
    "is_shut_down",
    "mark_shut_down",
    "open_unit",
    "open_units",
    "participants_of",
    "participating",
    "refuse_during_singleton_build",
    "units_drained",
]


@final
class Unit:
    """One unit of work: the engine it was opened on, and its scope until it exits.

    A context copied while the unit is open — a task it started, a request a
    server began from an earlier one's context — keeps pointing at it after it
    is over, and so does every container handed out for it. The scope is
    dropped at the exit so such a context finds no unit there, and such a
    container refuses to resolve, rather than handing out scoped services
    that have been released.
    """

    __slots__ = ("engine", "scope")

    def __init__(self, engine: AsyncContainer, scope: ScopedAsyncContainer) -> None:
        self.engine = engine
        self.scope: ScopedAsyncContainer | None = scope

    @property
    def closed(self) -> bool:
        """Whether the unit has exited, its scoped services released."""
        return self.scope is None


# The units of work this context was handed, innermost last; each open for as
# long as it holds a scope. A chain, not one slot, so the units of several
# kernels nest: a unit of one kernel opened inside another kernel's still
# finds the outer one of its own kernel.
_current: ContextVar[tuple[Unit, ...]] = ContextVar(
    "xtr_dependency_injection_unit_of_work", default=()
)
# A new connection carries no unit of work, whatever context its task was copied from.
register_detached_variable(_current, ())


def current_unit_record() -> Unit | None:
    """Return the innermost unit of work open in this context, if any."""
    return next((unit for unit in reversed(_current.get()) if not unit.closed), None)


def open_unit(engine: AsyncContainer) -> Unit | None:
    """Return the innermost unit of work open in this context on ``engine``, if any.

    A unit another engine opened — a second kernel's — is not ``engine``'s to join.
    """
    return next(
        (unit for unit in reversed(_current.get()) if unit.engine is engine and not unit.closed),
        None,
    )


@contextmanager
def entered(engine: AsyncContainer, scope: ScopedAsyncContainer) -> Generator[Unit]:
    """Make ``scope`` of ``engine`` this context's unit of work until the block exits.

    The unit is closed first, for every context that carries it, so a block
    exited from another context than the one it was entered in — a context
    manager handed to another task — still leaves no context finding it open.
    """
    unit = Unit(engine, scope)
    token = _current.set((*_current.get(), unit))
    try:
        yield unit
    finally:
        unit.scope = None
        # Refused when the exiting context is not the one that entered: it
        # never held this unit, so there is nothing of ours to restore there.
        with suppress(ValueError):
            _current.reset(token)


@final
class _Units:
    """How many units of one engine are open, who waits for none to be, and whether it shut down."""

    __slots__ = ("open", "shut_down", "waiters")

    def __init__(self) -> None:
        self.open = 0
        self.shut_down = False
        self.waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[None]]] = []


# Per engine. Units of one engine may run on several threads' loops, so it is
# guarded by a lock, and a waiter is woken on its own loop.
#
# Keyed by the engine's override manager, not the engine: wireup's containers
# take no weak reference (they declare ``__slots__`` without one), and the
# override manager is the one object wireup gives each root container through
# its public API that it shares with every scope of that container and that
# nothing else holds — so an entry goes with its engine.
_UNITS: weakref.WeakKeyDictionary[object, _Units] = weakref.WeakKeyDictionary()
_UNITS_LOCK = threading.Lock()


def _units_of(engine: AsyncContainer) -> _Units:
    units = _UNITS.get(engine.override)
    if units is None:
        units = _UNITS.setdefault(engine.override, _Units())
    return units


@contextmanager
def counted(engine: AsyncContainer) -> Generator[None]:
    """Count a unit of ``engine`` as open until the block exits — its teardown included.

    Its scoped services still use the engine's singletons until they are
    closed, so the unit is open until then; a shutdown waiting for none to be
    is woken when the last one closes, from whichever context it closes in.
    """
    with _UNITS_LOCK:
        units = _units_of(engine)
        units.open += 1
    try:
        yield
    finally:
        with _UNITS_LOCK:
            units.open -= 1
            woken = units.waiters if units.open == 0 else []
            if woken:
                units.waiters = []
        for loop, waiter in woken:
            # Refused by a loop closed while it waited: nothing is left there to wake,
            # and the unit's own outcome must not be replaced by that refusal.
            with suppress(RuntimeError):
                _ = loop.call_soon_threadsafe(_wake, waiter)


def _wake(waiter: asyncio.Future[None]) -> None:
    if not waiter.done():
        waiter.set_result(None)


def open_units(engine: AsyncContainer) -> int:
    """Return how many units of ``engine`` are open, their teardown included."""
    with _UNITS_LOCK:
        units = _UNITS.get(engine.override)
        return 0 if units is None else units.open


async def units_drained(engine: AsyncContainer, within: float) -> int:
    """Wait up to ``within`` seconds for every unit of ``engine`` to close.

    Returns:
        How many are still open once it stopped waiting.
    """
    loop = asyncio.get_running_loop()
    waiter: asyncio.Future[None] = loop.create_future()
    with _UNITS_LOCK:
        units = _units_of(engine)
        if units.open == 0:
            return 0
        units.waiters.append((loop, waiter))
    try:
        _ = await asyncio.wait((waiter,), timeout=within)
    finally:
        with _UNITS_LOCK, suppress(ValueError):
            units.waiters.remove((loop, waiter))
    return open_units(engine)


def mark_shut_down(engine: AsyncContainer) -> None:
    """Record that ``engine``'s kernel shut down, so nothing resolves from it any more."""
    with _UNITS_LOCK:
        _units_of(engine).shut_down = True


def is_shut_down(engine: AsyncContainer) -> bool:
    """Tell whether ``engine``'s kernel shut down."""
    with _UNITS_LOCK:
        units = _UNITS.get(engine.override)
        return units is not None and units.shut_down


# True while a singleton's factory runs, in a kernel built in debug mode only:
# outside debug nothing sets it, so production never pays for or trips on it.
_BUILDING_SINGLETON: ContextVar[bool] = ContextVar(
    "xtr_dependency_injection_building_singleton", default=False
)


@contextmanager
def building_singleton() -> Generator[None]:
    """Say a singleton is being built in this context until the block exits."""
    token = _BUILDING_SINGLETON.set(True)
    try:
        yield
    finally:
        _BUILDING_SINGLETON.reset(token)


def refuse_during_singleton_build(read: str) -> None:
    """Refuse to read ``read`` — something per unit of work — while a singleton is being built.

    Raises:
        UnitReadDuringSingletonBuildError: If a singleton is being built here.
    """
    if _BUILDING_SINGLETON.get():
        raise UnitReadDuringSingletonBuildError(read)


@final
class UnitParticipants:
    """Every service tagged ``kernel.unit_participant``, in the order they are told."""

    __slots__ = ("participants",)

    def __init__(self, participants: Sequence[UnitParticipantInterface]) -> None:
        self.participants: tuple[UnitParticipantInterface, ...] = tuple(participants)


async def participants_of(engine: AsyncContainer) -> tuple[UnitParticipantInterface, ...]:
    """Return the participants told of every unit of work ``engine`` opens.

    Built the first time a unit opens rather than at boot, so a container
    never booted — one ``create_container`` compiled, one attached without a
    lifespan — still tells them; looked up before the unit is set, so their
    construction reads no unit. An engine no kernel compiled has none. The
    collection is a singleton, so the engine itself keeps it once built.
    """
    try:
        return (await engine.get(UnitParticipants)).participants
    except UnknownServiceRequestedError:
        return ()


@contextmanager
def participating(participants: Sequence[UnitParticipantInterface]) -> Generator[None]:
    """Tell ``participants`` a unit of work begins, and that it ended once the block exits.

    Each is told it began in order, and it ended in reverse, handed back
    what it returned when it began. The tokens stay in this frame, never in
    a context variable, so a unit exited from another context still hands
    each participant its own.

    Raises:
        ExceptionGroup: When a participant fails to begin — those already
            begun are ended, and the block does not run — or, the block
            having succeeded, when any fails to end. A failure to end while
            the block raised is a note on the block's exception instead.
    """
    began: list[tuple[UnitParticipantInterface, object | None]] = []
    for participant in participants:
        try:
            began.append((participant, participant.unit_began()))
        except Exception as error:  # noqa: BLE001 — raised below, with any failure to end the ones begun
            failures = [error, *(failure for _, failure in _ended(began))]
            raise ExceptionGroup("a unit participant failed to begin the unit", failures) from None
    try:
        yield
    except BaseException as error:
        for participant, failure in _ended(began):
            error.add_note(
                f"{type(participant).__qualname__}.unit_ended failed: {safe_repr(failure)}"
            )
        raise
    failures = [failure for _, failure in _ended(began)]
    if failures:
        raise ExceptionGroup("a unit participant failed to end the unit", failures)


def _ended(
    began: Sequence[tuple[UnitParticipantInterface, object | None]],
) -> list[tuple[UnitParticipantInterface, Exception]]:
    """End every participant in ``began``, last first; return the ones that failed."""
    failures: list[tuple[UnitParticipantInterface, Exception]] = []
    for participant, token in reversed(began):
        try:
            participant.unit_ended(token)
        except Exception as error:  # noqa: BLE001 — collected: every participant is ended whatever another does
            failures.append((participant, error))
    return failures
