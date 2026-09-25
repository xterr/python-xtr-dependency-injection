"""Keeping an object to some environments: ``@when`` and ``@when_not``.

Put either on anything the kernel scans — a service, a command, a handler, a
``@configure`` function — in any order with any other decorator. An object
left out of the environment is not collected at all, as if it did not
exist; the scan report says why.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, TypeVar, cast

from ._marker import own_marker, set_marker

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["matches_env", "when", "when_envs_of", "when_not", "when_not_envs_of"]

T = TypeVar("T")

_WHEN: Final = "__xtr_when__"
_WHEN_NOT: Final = "__xtr_when_not__"


def when(env: str, /, *envs: str) -> Callable[[T], T]:
    """Keep the decorated object to the given environments.

    Repeating it widens the set: ``@when("dev") @when("test")`` is
    ``@when("dev", "test")``.
    """
    return _adding(_WHEN, (env, *envs))


def when_not(env: str, /, *envs: str) -> Callable[[T], T]:
    """Leave the decorated object out of the given environments.

    Repeating it widens the set. Combined with ``@when``, both must pass.
    """
    return _adding(_WHEN_NOT, (env, *envs))


def when_envs_of(obj: object) -> frozenset[str] | None:
    """Return the environments ``@when`` keeps ``obj`` to, or ``None`` if unrestricted."""
    return cast("frozenset[str] | None", own_marker(obj, _WHEN))


def when_not_envs_of(obj: object) -> frozenset[str] | None:
    """Return the environments ``@when_not`` leaves ``obj`` out of, or ``None``."""
    return cast("frozenset[str] | None", own_marker(obj, _WHEN_NOT))


def matches_env(obj: object, env: str) -> bool:
    """Return whether ``obj`` belongs in ``env`` under its ``@when`` and ``@when_not``."""
    included = when_envs_of(obj)
    excluded = when_not_envs_of(obj)
    return (included is None or env in included) and (excluded is None or env not in excluded)


def _adding(name: str, envs: tuple[str, ...]) -> Callable[[T], T]:
    def decorate(obj: T) -> T:
        current = cast("frozenset[str] | None", own_marker(obj, name)) or frozenset()
        return set_marker(obj, name, current | frozenset(envs))

    return decorate
