"""Parameters that also answer ``env(...)``: the bag the container is built with.

``get("env(int:PORT)")`` returns the placeholder ``env("int:PORT")``, so a
``"%env(int:PORT)%"`` string resolves to it — typed when it is the whole
string, its token when embedded. The bag remembers every placeholder it
handed out, and the types each processor prefix produces, recorded by
``RegisterEnvVarProcessorsPass``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from typing_extensions import override

from xtr_dependency_injection.config.env_placeholder import EnvPlaceholder, placeholder

from .parameter_bag import ParameterBag

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["EnvPlaceholderParameterBag"]


@final
class EnvPlaceholderParameterBag(ParameterBag):
    """A :class:`ParameterBag` resolving ``env(...)`` names to placeholders."""

    __slots__: tuple[str, ...] = ("_env_placeholders", "_provided_types")

    def __init__(self, parameters: Mapping[str, object] | None = None) -> None:
        """Start with ``parameters``, no placeholder handed out, no provided type known."""
        super().__init__(parameters)
        self._env_placeholders: dict[str, EnvPlaceholder] = {}
        self._provided_types: dict[str, str] = {}

    @override
    def get(self, name: str, /) -> object:
        if name.startswith("env(") and name.endswith(")"):
            expression = name[4:-1]
            made = placeholder(expression)
            self._env_placeholders[expression] = made
            return made
        return super().get(name)

    def get_env_placeholders(self) -> dict[str, EnvPlaceholder]:
        """Return every placeholder a ``%env(...)%`` reference produced, by expression."""
        return dict(self._env_placeholders)

    def set_provided_types(self, provided_types: Mapping[str, str], /) -> None:
        """Record what each processor prefix produces (``"int"``, ``"bool|string"``)."""
        self._provided_types = dict(provided_types)

    def get_provided_types(self) -> dict[str, str]:
        """Return what each processor prefix produces."""
        return dict(self._provided_types)
