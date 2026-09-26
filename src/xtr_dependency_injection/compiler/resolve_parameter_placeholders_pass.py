"""Resolving ``%name%`` references inside the parameters themselves.

Every parameter source — the kernel's, each bundle's, each ``@parameters``
function's — is resolved against the parameters as a whole, so the engine
receives plain values: ``"%kernel.project_dir%/var"`` becomes the path, and
``"%env(DSN)%"`` the placeholder injections resolve when a service is built.
Every definition's arguments are resolved the same way. Bundle configs are
resolved earlier, by the merge pass, before each bundle loads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, final

from ._state import state_of

if TYPE_CHECKING:
    from collections.abc import Mapping

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

__all__ = ["ResolveParameterPlaceHoldersPass"]


@final
class ResolveParameterPlaceHoldersPass:
    """Replaces every parameter source, and every definition's arguments, by its resolved form."""

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Resolve every parameter source against all of them, as they were stored.

        Raises:
            ParameterNotFoundError: If a reference names no parameter.
            ParameterCircularReferenceError: If references loop.
            InvalidParameterTypeError: If an embedded reference names
                something other than a string or a number.
        """
        state = state_of(builder)
        bag = state.parameter_bag
        for definition in builder.get_definitions():
            if definition.arguments:
                resolved_arguments = bag.unescape_value(bag.resolve_value(definition.arguments))
                _ = definition.set_arguments(cast("Mapping[str, object]", resolved_arguments))
        state.parameters[:] = [
            (origin, cast("Mapping[str, object]", bag.unescape_value(bag.resolve_value(values))))
            for origin, values in state.parameters
        ]
        bag.resolve()
        resolved = bag.unescape_value(bag.all())
        bag.clear()
        bag.add(cast("dict[str, object]", resolved))
