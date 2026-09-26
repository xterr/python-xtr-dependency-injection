"""Removing the definitions whose ``container.remove_if_missing`` conditions are not met.

A tag is a set of independent conditions — ``service`` (with an optional
``qualifier``), ``class_`` and ``package`` — and a definition survives only
while every attribute of every tag on it holds. Removing a definition can turn
another condition false, so the container is swept until it settles.
"""

from __future__ import annotations

import importlib
from importlib.metadata import PackageNotFoundError, distribution
from typing import TYPE_CHECKING, Final, cast, final

from xtr_dependency_injection.decorator.remove_if_missing import REMOVE_IF_MISSING_TAG
from xtr_dependency_injection.exception import InvalidDefinitionError, UnknownServiceError
from xtr_dependency_injection.exception._naming import key_name

if TYPE_CHECKING:
    from collections.abc import Hashable, Mapping

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.definition import ServiceKey

__all__ = ["RemoveMissingDependenciesPass"]

_ATTRIBUTES: Final = frozenset({"service", "qualifier", "class_", "package"})
_CONDITIONS: Final = ("service", "class_", "package")


@final
class RemoveMissingDependenciesPass:
    """Drops every definition a ``container.remove_if_missing`` tag no longer allows.

    ``class_`` carries a trailing underscore because ``class`` is a reserved
    word. When a definition is dropped, every alias pointing at it is dropped
    too, so nothing is left dangling.
    """

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Sweep the tagged definitions until no further one is removed.

        Raises:
            InvalidDefinitionError: If a tag has an unknown attribute, or none
                of ``service``, ``class_`` and ``package``.
        """
        tagged = builder.find_tagged_service_ids(REMOVE_IF_MISSING_TAG)
        if not tagged:
            return
        for key, tags in tagged.items():
            for tag in tags:
                _validate(key, tag)
        removed = True
        while removed:
            removed = False
            for key, tags in tagged.items():
                if not builder.has_definition(*key):
                    continue
                for tag in tags:
                    reason = _unmet(builder, tag)
                    if reason is None:
                        continue
                    self._remove(builder, key, reason)
                    removed = True
                    break

    def _remove(self, builder: ContainerBuilder, key: ServiceKey, reason: str) -> None:
        """Drop ``key`` — a definition or an alias — and every alias pointing at it."""
        if builder.has_definition(*key):
            builder.remove_definition(*key)
        else:
            builder.remove_alias(*key)
        builder.log(self, f"Removed service {key_name(key)}; reason: {reason}.")
        for alias, target in builder.get_aliases().items():
            if target == key:
                self._remove(builder, alias, f"it aliases {key_name(key)}")


def _validate(key: ServiceKey, tag: Mapping[str, object]) -> None:
    unknown = sorted(set(tag) - _ATTRIBUTES)
    if unknown:
        raise InvalidDefinitionError(
            key,
            f"unknown {REMOVE_IF_MISSING_TAG} attribute {unknown[0]!r}, expected one of "
            + ", ".join(sorted(_ATTRIBUTES)),
        )
    if not any(tag.get(condition) is not None for condition in _CONDITIONS):
        raise InvalidDefinitionError(
            key, f"a {REMOVE_IF_MISSING_TAG} tag needs one of service, class_ or package"
        )


def _unmet(builder: ContainerBuilder, tag: Mapping[str, object]) -> str | None:
    """Return why ``tag`` does not hold, or ``None`` when every condition does."""
    service = tag.get("service")
    if service is not None:
        key = (cast("type", service), cast("Hashable | None", tag.get("qualifier")))
        if not _resolves(builder, key):
            return f"service {key_name(key)} is missing"
    class_path = tag.get("class_")
    if class_path is not None and not _class_importable(cast("str", class_path)):
        return f"class {class_path} is missing"
    package = tag.get("package")
    if package is not None and not _package_installed(cast("str", package)):
        return f"package {package} is missing"
    return None


def _resolves(builder: ContainerBuilder, key: ServiceKey) -> bool:
    """Return whether ``key`` reaches a definition, through its aliases.

    ``has`` answers true for an alias whose target is gone, so the aliases are
    followed to the definition.
    """
    try:
        _ = builder.find_definition(*key)
    except UnknownServiceError:
        return False
    return True


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
    try:
        _ = distribution(name)
    except PackageNotFoundError:
        return False
    return True
