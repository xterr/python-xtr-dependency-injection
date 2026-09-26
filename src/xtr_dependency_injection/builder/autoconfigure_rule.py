"""One ``register_for_autoconfiguration`` rule — a nominal subclass match.

The kernel's autoconfigure step applies every rule to every definition whose
built type has the rule's ``type_`` in its ``__mro__`` (a nominal subclass
check, not a structural check). Kernel-origin definitions are never
autoconfigured. A tag name already present on a definition wins over the
rule's — explicit stays.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .definition import Lifetime

__all__ = ["AutoconfigureRule"]


@dataclass(slots=True)
class AutoconfigureRule:
    """How to autoconfigure every subclass of ``type_``.

    Returned by :meth:`ContainerBuilder.register_for_autoconfiguration` for
    the caller to mutate through :meth:`add_tag`.

    Attributes:
        type_: The base type this rule applies to (nominal subclass match).
        tags: Tag name → list of attribute mappings, added to matched
            definitions. A ``callable`` in an attribute value is invoked with
            the concrete built class and must return the attribute mapping.
        lifetime: If not ``None``, the lifetime to give a matched definition.
    """

    type_: type
    tags: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    lifetime: Lifetime | None = None

    def add_tag(self, name: str, /, **attributes: object) -> AutoconfigureRule:
        """Add tag ``name`` with ``attributes``.

        Repeatable: each call appends one attribute mapping under ``name``.
        """
        self.tags.setdefault(name, []).append(dict(attributes))
        return self
