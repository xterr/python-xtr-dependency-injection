"""What every compiler pass implements: one ``process`` over the whole container."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

__all__ = ["CompilerPassInterface"]


@runtime_checkable
class CompilerPassInterface(Protocol):
    """A step of the compilation that sees, and may change, every definition.

    A pass is registered with a stage and a priority — through
    ``ContainerBuilder.add_compiler_pass`` from a bundle's ``build``, or
    ``@compiler_pass`` on a scanned class — and the compiler hands it a
    :class:`ContainerBuilder` bound to whoever registered it, so what the pass
    defines carries that origin. A bundle overriding ``process`` is itself a
    pass.
    """

    def process(self, builder: ContainerBuilder) -> None:
        """Inspect and adjust the container being built."""
        ...
