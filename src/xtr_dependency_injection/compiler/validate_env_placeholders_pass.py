"""Checking every environment placeholder in configs, parameters and arguments before running.

A placeholder is read only when a service needs it, so a mistake in one
would otherwise surface on first use. The pass fails the build instead on:

- a prefix no processor provides (``env("itn:PORT")``);
- a placeholder embedded in a longer string whose outer prefix produces
  something other than a string, number or bool (``f"x{env('json:X')}"``).

Arguments of ``key:``, ``enum:`` and ``default:`` are skipped: in
``key:host:json:DSN``, ``host`` is a key, not a prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final

from xtr_dependency_injection.config.env_placeholder import (
    env_placeholders_embedded_in,
    env_placeholders_in,
)
from xtr_dependency_injection.exception import EnvPlaceholderError

from ._state import state_of

if TYPE_CHECKING:
    from collections.abc import Mapping

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

__all__ = ["ValidateEnvPlaceholdersPass"]

_WITH_ARGUMENT: Final = frozenset({"key", "enum", "default"})
_EMBEDDABLE: Final = frozenset({"bool", "int", "float", "string"})


@final
class ValidateEnvPlaceholdersPass:
    """Fails the build on a placeholder no processor could resolve, or that cannot be embedded."""

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Check the placeholders of every resolved config, parameter and definition argument.

        Raises:
            EnvPlaceholderError: On an unknown prefix, or a non-scalar
                placeholder embedded in a string.
        """
        state = state_of(builder)
        types = state.parameter_bag.get_provided_types()
        values = [
            *state.configs.values(),
            *(values for _, values in state.parameters),
            *(definition.arguments for definition in builder.get_definitions()),
        ]
        for value in values:
            for held in env_placeholders_in(value):
                _check_prefixes(held.expression, types)
            for held in env_placeholders_embedded_in(value):
                outer = _outer_prefix(held.expression)
                declared = set(types.get(outer, "string").split("|"))
                if held.cast is not None or not declared <= _EMBEDDABLE:
                    reason = (
                        f"it is embedded in a string, but {outer!r} produces "
                        f"{'|'.join(sorted(declared))}: only strings, numbers and bools can be"
                    )
                    raise EnvPlaceholderError(held.expression, reason)


def _outer_prefix(expression: str) -> str:
    prefix, separator, _ = expression.partition(":")
    return prefix if separator else "string"


def _check_prefixes(expression: str, types: Mapping[str, str]) -> None:
    rest = expression
    while ":" in rest:
        prefix, _, rest = rest.partition(":")
        if prefix not in types:
            known = ", ".join(sorted(types))
            raise EnvPlaceholderError(
                expression, f"unsupported env var prefix {prefix!r}; the prefixes are {known}"
            )
        if prefix in _WITH_ARGUMENT:
            _, _, rest = rest.partition(":")
