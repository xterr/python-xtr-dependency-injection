"""Declaring a bundle's required peers.

Repeatable per class; each application records the peer as a class or as a
``"module:Class"`` string imported lazily by the resolver.
``ignore_on_invalid`` skips a target the resolver cannot import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, TypeVar, cast

from xtr_dependency_injection.exception import BundleDefinitionError

from .bundle import AnyBundle

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "REQUIRED_BUNDLES_ATTRIBUTE",
    "RequiredBundle",
    "required_bundle",
    "required_bundles_of",
]

REQUIRED_BUNDLES_ATTRIBUTE: Final = "__xtr_required_bundles__"
"""Where ``@required_bundle`` records its declarations, one tuple per class."""

_STRING_TARGET: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")

B = TypeVar("B", bound=type[AnyBundle])


@dataclass(frozen=True, slots=True)
class RequiredBundle:
    """One ``@required_bundle`` declaration on a bundle class.

    Attributes:
        target: The peer's class, or ``"module:Class"`` for lazy import.
        ignore_on_invalid: When the string target cannot be imported, the
            resolver reports it as skipped instead of raising.
    """

    target: str | type[AnyBundle]
    ignore_on_invalid: bool = False


def required_bundle(
    target: str | type[AnyBundle],
    /,
    *,
    ignore_on_invalid: bool = False,
) -> Callable[[B], B]:
    """Declare that the decorated bundle requires ``target`` to be active.

    Repeatable: each call appends one :class:`RequiredBundle` to the class's
    ``__xtr_required_bundles__`` tuple, in decoration order top-down. String
    targets are ``"module:Class"`` and imported lazily by the resolver.

    Args:
        target: The peer bundle class, or ``"module:Class"``.
        ignore_on_invalid: When ``target`` is a string that cannot be
            imported at resolve time, skip it silently instead of raising.

    Raises:
        BundleDefinitionError: If the string target does not have the shape
            ``"module:Class"``.
    """
    if isinstance(target, str) and not _STRING_TARGET.match(target):
        raise BundleDefinitionError(target, "a string required_bundle target is 'module:Class'")
    declaration = RequiredBundle(target=target, ignore_on_invalid=ignore_on_invalid)

    def declare(cls: B) -> B:
        existing = cast(
            "tuple[RequiredBundle, ...]",
            vars(cls).get(REQUIRED_BUNDLES_ATTRIBUTE, ()),
        )
        setattr(cls, REQUIRED_BUNDLES_ATTRIBUTE, (*existing, declaration))
        return cls

    return declare


def required_bundles_of(cls: type[AnyBundle]) -> tuple[RequiredBundle, ...]:
    """Return the declarations ``@required_bundle`` recorded on ``cls`` itself.

    Reads only the class's own attribute — declarations on a base class are
    not inherited.
    """
    return cast(
        "tuple[RequiredBundle, ...]",
        vars(cls).get(REQUIRED_BUNDLES_ATTRIBUTE, ()),
    )
