"""The built-in ``AFTER_REMOVING`` pass: turn every alias into a forwarding definition.

Runs after removal and fails on an alias whose target no longer exists.
Each surviving ``(alias -> target)`` also becomes a factory definition
producing the target's instance under the alias key, and the build state is
frozen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from xtr_dependency_injection.builder.definition import Definition, Origin
from xtr_dependency_injection.compiler.registration import _alias_factory
from xtr_dependency_injection.exception import UnknownServiceError

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

__all__ = ["validate_aliases_pass"]


def validate_aliases_pass(builder: ContainerBuilder) -> None:
    """AFTER_REMOVING built-in: turn each alias into a forwarding definition and freeze.

    Every ``(alias_key -> target_key)`` becomes a factory definition producing
    the target's instance under the alias key. A
    missing target — a raised ``UnknownServiceError`` — means an
    ``@as_alias`` (or an explicit ``set_alias``/``alias``) that referred to
    a service that never existed, or that a preceding ``BEFORE_REMOVING``
    pass removed the target without dropping the alias.

    Raises:
        UnknownServiceError: If an alias target is not defined.
    """
    state = builder._state  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] — the built-in pass reads state directly.
    for alias_key, target_key in state.aliases.items():
        if state.store.get(alias_key) is not None:
            continue
        target = state.store.get(target_key)
        if target is None:
            raise UnknownServiceError(alias_key, "set_alias")
        alias_type, alias_qualifier = alias_key
        target_type, target_qualifier = target_key
        factory = _alias_factory(alias_type, target_type, target_qualifier)
        state.store.add(
            Definition(
                key=(alias_type, alias_qualifier),
                provider=factory,
                kind="factory",
                lifetime=target.lifetime,
                origin=Origin(target.origin.kind, target.origin.name, "alias"),
            )
        )
    state.phase = "frozen"
