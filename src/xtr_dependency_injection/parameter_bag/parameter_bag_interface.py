"""What holds the container's parameters and resolves ``%name%`` references against them."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["ParameterBagInterface"]


@runtime_checkable
class ParameterBagInterface(Protocol):
    """The container's parameters, by dotted name (``kernel.project_dir``).

    Parameters nest: setting ``app.mailer.host`` makes ``app`` a mapping, and
    ``get("app")`` returns it whole.
    """

    def clear(self) -> None:
        """Remove every parameter."""
        ...

    def add(self, parameters: Mapping[str, object], /) -> None:
        """Merge ``parameters`` in, nested mappings merged and leaves replaced."""
        ...

    def all(self) -> dict[str, object]:
        """Return every parameter, nested."""
        ...

    def get(self, name: str, /) -> object:
        """Return the parameter ``name``.

        Raises:
            ParameterNotFoundError: If no such parameter exists.
        """
        ...

    def remove(self, name: str, /) -> None:
        """Remove the parameter ``name``, if set."""
        ...

    def set(self, name: str, value: object, /) -> None:
        """Set the parameter ``name`` to ``value``."""
        ...

    def has(self, name: str, /) -> bool:
        """Return whether the parameter ``name`` is set."""
        ...

    def resolve(self) -> None:
        """Replace every ``%name%`` reference in every parameter by its value."""
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
