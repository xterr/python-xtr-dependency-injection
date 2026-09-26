"""Mark a class definition to be removed when a dependency is missing.

The ``container.remove_if_missing`` tag: a definition carrying this tag is
dropped by ``RemoveMissingDependenciesPass`` when any of its conditions
is unmet. The decorator is repeatable: each call appends one tag attribute
mapping, and every tag must hold.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable

__all__ = ["REMOVE_IF_MISSING_TAG", "markers_of", "remove_if_missing"]

REMOVE_IF_MISSING_TAG: Final = "container.remove_if_missing"
"""The tag name; ``RemoveMissingDependenciesPass`` reads it."""

_ATTRIBUTE: Final = "__xtr_remove_if_missing__"

T = TypeVar("T", bound=type)


def remove_if_missing(
    *,
    service: type | None = None,
    qualifier: Hashable | None = None,
    class_: str | None = None,
    package: str | None = None,
) -> Callable[[T], T]:
    """Decorate a class so its definition is removed when a dependency is missing.

    ``service``, ``class_`` and ``package`` are each an independent
    condition, and any non-empty combination may be given in one call; every
    condition of a tag must hold for the definition to survive.

    Args:
        service: A service type whose definition (or alias) must exist. When
            given with ``qualifier``, the check is scoped to
            ``(service, qualifier)``.
        qualifier: Optional qualifier paired with ``service``.
        class_: A ``"module:Class"`` path; the removal fires when
            ``importlib.import_module(module)`` or ``getattr(module, Class)``
            fails. The trailing underscore in ``class_`` avoids the
            reserved word ``class``.
        package: A distribution name; the removal fires when
            ``importlib.metadata.distribution(package)`` raises. Parent-package
            checks are not supported.

    Repeatable: each call appends one tag attribute mapping; every tag must
    hold for the definition to survive.

    Raises:
        TypeError: If none of ``service``/``class_``/``package`` is given, or
            if ``qualifier`` is given without ``service``.
    """
    provided = [
        name
        for name, value in (("service", service), ("class_", class_), ("package", package))
        if value is not None
    ]
    if not provided:
        msg = "@remove_if_missing requires one of service=, class_= or package="
        raise TypeError(msg)
    if qualifier is not None and service is None:
        msg = "@remove_if_missing qualifier= only makes sense with service="
        raise TypeError(msg)

    attributes: dict[str, object] = {}
    if service is not None:
        attributes["service"] = service
        if qualifier is not None:
            attributes["qualifier"] = qualifier
    if class_ is not None:
        attributes["class_"] = class_
    if package is not None:
        attributes["package"] = package

    def record(target: T) -> T:
        existing = cast("list[dict[str, object]]", target.__dict__.get(_ATTRIBUTE, []))
        # Copy on write so a subclass never mutates a parent's list.
        merged = [*existing, attributes]
        setattr(target, _ATTRIBUTE, merged)
        return target

    return record


def markers_of(obj: object) -> list[dict[str, object]]:
    """Return every ``@remove_if_missing`` attribute mapping recorded on ``obj`` itself."""
    namespace = cast("dict[str, object]", getattr(obj, "__dict__", {}))
    return list(cast("list[dict[str, object]]", namespace.get(_ATTRIBUTE, [])))
