"""The built-in passes' one way into the build state behind a builder.

A user pass works through the public :class:`ContainerBuilder` API. The
built-in passes also need what that API does not expose — the scan's
candidates, the autoconfiguration rules, the decoration table — so they read
the shared build state here, in one place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.service_configurator import BuildState

__all__ = ["state_of"]


def state_of(builder: ContainerBuilder) -> BuildState:
    """Return the build state ``builder`` is a view of."""
    return builder._state  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] — built-in passes share the build state.
