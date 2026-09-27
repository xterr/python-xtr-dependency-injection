"""Checking every ``kernel.reset`` tag names a method its service has.

The :class:`~xtr_dependency_injection.runtime.services_resetter.ServicesResetter`
calls that method on every built service between units of work; a wrong name
would only fail on the first reset, long after the container was built.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final

from xtr_dependency_injection.exception import InvalidDefinitionError

from ._wireup_bridge import built_type

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.definition import ServiceKey

__all__ = ["RESET_TAG", "ResettableServicePass", "not_weak_referenceable"]

RESET_TAG: Final = "kernel.reset"
"""The tag a resettable service carries; its ``method`` attribute names the reset method."""


@final
class ResettableServicePass:
    """Fails the build on a ``kernel.reset`` tag without a usable ``method``.

    Registered by the kernel bundle. A service whose built type cannot be
    known — a factory without a return annotation — is not checked.
    """

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Check the ``method`` attribute of every ``kernel.reset`` tag.

        Raises:
            InvalidDefinitionError: If a tag has no string ``method``, the
                service's built type has no such callable attribute, or a
                scoped or transient class cannot be weak-referenced.
        """
        for key, tags in builder.find_tagged_service_ids(RESET_TAG).items():
            definition = builder.get_definition(*key)
            built = built_type(definition)
            if (
                definition.kind == "class"
                and definition.lifetime != "singleton"
                and built is not None
                and not _weak_referenceable(built)
            ):
                raise not_weak_referenceable(key, definition.lifetime)
            for attributes in tags:
                method = attributes.get("method")
                if not isinstance(method, str):
                    raise InvalidDefinitionError(
                        key, f'tag "{RESET_TAG}" requires a string "method" attribute'
                    )
                if built is not None and not callable(getattr(built, method, None)):
                    raise InvalidDefinitionError(
                        key, f'tag "{RESET_TAG}" names method {method!r}, which it does not have'
                    )


def not_weak_referenceable(key: ServiceKey, lifetime: str) -> InvalidDefinitionError:
    """Return the error for a short-lived resettable service whose instances refuse weak references.

    The resetter would have to hold every instance built, forever.
    """
    reason = (
        f'tag "{RESET_TAG}" on a {lifetime} service needs instances '
        'that can be weak-referenced: add "__weakref__" to its __slots__'
    )
    return InvalidDefinitionError(key, reason)


def _weak_referenceable(cls: type) -> bool:
    """Return whether instances of ``cls`` accept a weak reference."""
    return getattr(cls, "__weakrefoffset__", 1) != 0
