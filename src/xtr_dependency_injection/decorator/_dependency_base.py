"""The shape the injection markers take when the web framework is installed.

With ``fastapi`` importable, :class:`~.autowire.Autowire` and
:class:`~.target.Target` subclass the framework's own dependency declaration,
so a route parameter annotated with one resolves through the container. When
it is absent — or for a type checker, always — they subclass an empty base,
so their public signatures never mention a framework type and nothing changes
for code that never serves an application.
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING, Final

from xtr_dependency_injection.exception import InvalidArgumentTypeError

if TYPE_CHECKING:
    from collections.abc import Hashable

__all__ = ["IS_DEPENDENCY", "DependencyBase", "set_dependency"]

IS_DEPENDENCY: Final = importlib.util.find_spec("fastapi") is not None
"""Whether the web framework is importable, decided once at import."""

if TYPE_CHECKING or not IS_DEPENDENCY:

    class DependencyBase:
        """What the markers subclass when the web framework is absent.

        Deliberately empty: without the framework a marker is a plain frozen
        dataclass, and a type checker always sees this shape, so no framework
        type leaks into a public signature.
        """

        __slots__: tuple[str, ...] = ()

else:
    # Runtime-only: a type checker treats TYPE_CHECKING as true and never
    # reaches this, so the markers' public shape stays framework-free.
    from fastapi.params import Depends as DependencyBase  # pyright: ignore[reportUnreachable]


_COPY_ARGUMENTS: Final = frozenset({"dependency", "use_cache", "scope"})
"""What the framework's route analysis passes when it copies a marker."""


def set_dependency(
    marker: object,
    given: dict[str, object],
    *,
    param: str | None = None,
    env: str | None = None,
    qualifier: Hashable | None = None,
) -> None:
    """Give ``marker`` the resolver the framework calls for it, in place.

    Called by a marker's ``__init__`` with ``given`` holding the keyword
    arguments the marker did not name itself. Without the framework any such
    argument is a mistake. With it, ``given`` is exactly what
    ``dataclasses.replace`` passes when the framework's route analysis copies
    a bare marker with the parameter's type as ``dependency`` — the moment a
    bare marker learns which service it stands for.

    Args:
        marker: The marker being built; its framework fields are written with
            ``object.__setattr__`` because the marker is frozen.
        given: The keyword arguments the marker's ``__init__`` collected.
        param: The dotted parameter name the marker injects, if any.
        env: The environment variable expression the marker injects, if any.
        qualifier: The qualifier a service resolution carries, if any.

    Raises:
        InvalidArgumentTypeError: If ``given`` holds anything the framework's
            copy never passes — every argument, when the framework is absent.
            Also a :class:`TypeError`, as an unexpected keyword always is.
    """
    unexpected = set(given) - _COPY_ARGUMENTS if IS_DEPENDENCY else set(given)
    if unexpected:
        msg = f"unexpected arguments: {', '.join(sorted(unexpected))}"
        raise InvalidArgumentTypeError(msg)
    if not IS_DEPENDENCY:
        return
    dependency = given.get("dependency")
    already_derived = getattr(dependency, "__xtr_provider__", False) is True
    if param is None and env is None and (dependency is None or already_derived):
        # A bare marker keeps what it was given: ``Injected`` is built while
        # this package itself imports, when the integration module below —
        # which imports back into this package — cannot be imported yet.
        resolved = dependency
    else:
        # This upward import is deliberately lazy, for the reason above: only
        # a marker that names what to inject, or one the framework already
        # handed a service type, ever needs a resolver.
        from xtr_dependency_injection.integration._resolvers import (  # noqa: PLC0415 — import cycle
            provider,
        )

        if param is not None:
            resolved = provider("param", param)
        elif env is not None:
            resolved = provider("env", env)
        else:
            resolved = provider("service", dependency, qualifier)
    object.__setattr__(marker, "dependency", resolved)
    object.__setattr__(marker, "use_cache", given.get("use_cache", True))
    object.__setattr__(marker, "scope", given.get("scope"))
