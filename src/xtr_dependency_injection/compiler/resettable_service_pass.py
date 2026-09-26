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

__all__ = ["RESET_TAG", "ResettableServicePass"]

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
            InvalidDefinitionError: If a tag has no string ``method``, or the
                service's built type has no such callable attribute.
        """
        for key, tags in builder.find_tagged_service_ids(RESET_TAG).items():
            built = built_type(builder.get_definition(*key))
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
