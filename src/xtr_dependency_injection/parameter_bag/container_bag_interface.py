"""What a service injects to read the compiled container's parameters."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["ContainerBagInterface"]


@runtime_checkable
class ContainerBagInterface(Protocol):
    """The container's parameters, read-only, as an injectable service."""

    def all(self) -> dict[str, object]:
        """Return every parameter, nested."""
        ...

    def get(self, name: str, /) -> object:
        """Return the parameter ``name``.

        Raises:
            ParameterNotFoundError: If no such parameter exists.
            EnvPlaceholderError: If it holds an environment placeholder,
                which is resolved when injected, not read raw.
        """
        ...

    def has(self, name: str, /) -> bool:
        """Return whether the parameter ``name`` exists."""
        ...

    def resolve_value(self, value: object, /) -> object:
        """Return ``value`` with every ``%name%`` reference in its strings resolved."""
        ...

    def escape_value(self, value: object, /) -> object:
        """Return ``value`` with every ``%`` in its strings escaped as ``%%``."""
        ...

    def unescape_value(self, value: object, /) -> object:
        """Return ``value`` with every ``%%`` in its strings turned back into ``%``."""
        ...
