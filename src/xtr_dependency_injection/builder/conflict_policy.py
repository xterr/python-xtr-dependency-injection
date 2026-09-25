"""Who wins when two definitions claim one key.

Checked before wireup ever sees the definitions, so an error names both
origins instead of a bare duplicate:

- the application over a bundle: the application wins, silently, and the
  report records the override (Symfony's parity);
- bundle against bundle: an error, unless it goes through
  ``builder.replace``;
- application against application: an error.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, final

from xtr_dependency_injection.exception import DuplicateServiceError

if TYPE_CHECKING:
    from .definition import Definition, Origin, ServiceKey

__all__ = ["DefinitionStore"]


@final
class DefinitionStore:
    """Every definition of one build, by key, in declaration order."""

    __slots__ = ("_counter", "_definitions", "_overrides", "_sequence")

    def __init__(self) -> None:
        """Start empty."""
        self._definitions: dict[ServiceKey, Definition] = {}
        self._overrides: dict[ServiceKey, list[Origin]] = {}
        self._sequence: dict[ServiceKey, int] = {}
        self._counter = 0

    def add(self, definition: Definition) -> None:
        """Add ``definition``, applying the conflict policy.

        Raises:
            DuplicateServiceError: If neither definition may override the
                other.
        """
        key = definition.key
        existing = self._definitions.get(key)
        if existing is None:
            self._insert(definition)
            return
        if definition.origin.kind == "app" and existing.origin.kind != "app":
            self._overrides.setdefault(key, []).append(existing.origin)
            self._insert(definition)
        elif existing.origin.kind == "app" and definition.origin.kind != "app":
            self._overrides.setdefault(key, []).append(definition.origin)
        else:
            raise DuplicateServiceError(key, existing.origin, definition.origin)

    def replace(self, definition: Definition) -> None:
        """Replace the definition of ``definition.key`` on purpose, keeping its position."""
        existing = self._definitions[definition.key]
        self._overrides.setdefault(definition.key, []).append(existing.origin)
        self._definitions[definition.key] = definition

    def update(self, key: ServiceKey, **changes: object) -> None:
        """Change fields of the definition of ``key`` without it counting as an override."""
        self._definitions[key] = replace(self._definitions[key], **changes)

    def remove(self, key: ServiceKey) -> None:
        """Forget the definition of ``key``."""
        del self._definitions[key]
        _ = self._sequence.pop(key, None)

    def get(self, key: ServiceKey) -> Definition | None:
        """Return the definition of ``key``, or ``None``."""
        return self._definitions.get(key)

    def has_provider(self, provider: object) -> bool:
        """Return whether any definition is provided by this very object."""
        return any(definition.provider is provider for definition in self._definitions.values())

    def definitions(self) -> tuple[Definition, ...]:
        """Return every definition, in declaration order."""
        ordered = sorted(self._definitions.values(), key=lambda d: self._sequence[d.key])
        return tuple(ordered)

    def overrides_of(self, key: ServiceKey) -> tuple[Origin, ...]:
        """Return the origins of the definitions ``key``'s replaced or outranked."""
        return tuple(self._overrides.get(key, ()))

    def _insert(self, definition: Definition) -> None:
        self._counter += 1
        self._definitions[definition.key] = definition
        self._sequence[definition.key] = self._counter
