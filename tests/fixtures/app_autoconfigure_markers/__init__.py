"""Fixtures for the ``@autoconfigure`` / ``@autoconfigure_tag`` marker tests."""

from __future__ import annotations

from typing_extensions import override
from xtr_service_contracts import ResetInterface

from xtr_dependency_injection.decorator.as_service import as_service
from xtr_dependency_injection.decorator.autoconfigure import autoconfigure, autoconfigure_tag


@autoconfigure(tags=(("marker.static", {"who": "alpha"}),))
@as_service()
class TaggedByAutoconfigure(ResetInterface):
    """Matched by its own ``@autoconfigure`` marker (nominal — cls in mro)."""

    def __init__(self) -> None:
        self.resets: int = 0

    @override
    def reset(self) -> None:
        self.resets += 1


def _from_class(cls: type) -> dict[str, object]:
    return {"cls_name": cls.__name__}


@autoconfigure(tags=(("marker.callable", _from_class),))
@as_service()
class TaggedWithCallable:
    """Tag attributes computed at apply time from the matched class."""


@autoconfigure_tag()
@as_service()
class DefaultTagName:
    """``@autoconfigure_tag()`` with no name → default = ``qualified_name``."""
