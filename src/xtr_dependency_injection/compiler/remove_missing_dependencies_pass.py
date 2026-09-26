"""The built-in ``BEFORE_REMOVING`` pass: drop definitions whose dependency is missing.

Every ``container.remove_if_missing`` tag is a set of independent conditions
— ``service``, ``class_``, ``package`` — and a definition survives only
while every tag on it holds. Removing one definition can invalidate
another's tag, so the pass sweeps until it settles.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, cast

from xtr_dependency_injection.decorator.remove_if_missing import REMOVE_IF_MISSING_TAG

if TYPE_CHECKING:
    from collections.abc import Mapping

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.definition import ServiceKey
    from xtr_dependency_injection.builder.service_configurator import BuildState

__all__ = ["remove_if_missing_pass"]


def remove_if_missing_pass(builder: ContainerBuilder) -> None:
    """BEFORE_REMOVING built-in: drop every definition whose ``container.remove_if_missing`` fails.

    A tag has ``service=<type>`` (with optional ``qualifier=``),
    ``class_="module:Class"`` and/or ``package="dist"``; every tag on a
    definition must hold, and every attribute of a tag must hold. Removing
    one definition can invalidate another's tag, so the pass sweeps until
    it settles. When a definition is dropped, any alias pointing at it is
    dropped too.

    ``service``, ``class_`` and ``package`` are each their own condition,
    checked independently — any non-empty combination may appear in one
    tag. ``class_`` carries a trailing underscore because ``class`` is a
    reserved word. ``parent_packages`` is not supported.
    """
    state = builder._state  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] — the built-in pass reads state directly.
    tagged: dict[ServiceKey, list[dict[str, object]]] = {
        definition.key: definition.get_tag(REMOVE_IF_MISSING_TAG)
        for definition in state.store.entries()
        if definition.has_tag(REMOVE_IF_MISSING_TAG)
    }
    if not tagged:
        return
    while True:
        removed = False
        for key in list(tagged):
            if state.store.get(key) is None:
                del tagged[key]
                continue
            for tag in tagged[key]:
                if _remove_if_missing_holds(state, tag):
                    continue
                _remove_with_aliases(state, key)
                del tagged[key]
                removed = True
                break
        if not removed:
            break


def _remove_if_missing_holds(state: BuildState, tag: Mapping[str, object]) -> bool:
    """Return whether every attribute of ``tag`` holds."""
    service = tag.get("service")
    if service is not None:
        qualifier = tag.get("qualifier")
        if not _alias_or_definition_of(state, (cast("type", service), qualifier)):
            return False
    class_path = tag.get("class_")
    if class_path is not None and not _class_importable(cast("str", class_path)):
        return False
    package = tag.get("package")
    return not (package is not None and not _package_installed(cast("str", package)))


def _alias_or_definition_of(state: BuildState, key: ServiceKey) -> bool:
    """Return whether ``key`` resolves — follows aliases without looping."""
    seen: set[ServiceKey] = set()
    while key in state.aliases and key not in seen:
        seen.add(key)
        key = state.aliases[key]
    return state.store.get(key) is not None


def _class_importable(path: str) -> bool:
    """Return whether ``"module:Class"`` resolves — imports lazily and swallows failure."""
    module, _, attribute = path.partition(":")
    if not module or not attribute:
        return False
    try:
        loaded = importlib.import_module(module)
    except ImportError:
        return False
    return hasattr(loaded, attribute)


def _package_installed(name: str) -> bool:
    """Return whether ``name`` is an installed distribution."""
    # Local import to keep the module import graph minimal.
    from importlib.metadata import PackageNotFoundError, distribution  # noqa: PLC0415

    try:
        _ = distribution(name)
    except PackageNotFoundError:
        return False
    return True


def _remove_with_aliases(state: BuildState, key: ServiceKey) -> None:
    """Drop ``key`` from the store and every alias pointing at it (recursively)."""
    if state.store.get(key) is not None:
        state.store.remove(key)
    dangling = [alias for alias, target in state.aliases.items() if target == key]
    for alias in dangling:
        del state.aliases[alias]
        _ = state.alias_origins.pop(alias, None)
        _remove_with_aliases(state, alias)
