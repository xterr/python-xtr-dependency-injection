"""What the builder holds: one definition per service key, and where each came from."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from typing_extensions import override

from .on_invalid import OnInvalid

__all__ = ["Decorates", "Definition", "Lifetime", "Origin", "ServiceKey"]

ServiceKey: TypeAlias = tuple[type, Hashable | None]
"""``(provided type, qualifier)`` — the identity wireup registers a service under."""

Lifetime: TypeAlias = Literal["singleton", "scoped", "transient"]
"""How long wireup keeps what a definition builds."""


@dataclass(frozen=True, slots=True)
class Origin:
    """Who contributed a definition: the kernel, a bundle, or the application.

    Attributes:
        kind: ``"kernel"``, ``"bundle"`` or ``"app"``.
        name: The bundle's name, or ``module:qualname`` of the application
            object.
        note: How it got there, when not directly — e.g.
            ``"via autoconfigure of app.x:Y"``.
    """

    kind: Literal["kernel", "bundle", "app"]
    name: str
    note: str | None = None

    @override
    def __str__(self) -> str:
        described = f"{self.kind} {self.name}"
        return described if self.note is None else f"{described} ({self.note})"


@dataclass(frozen=True, slots=True)
class Decorates:
    """What ``Definition.set_decorated_service`` records: a target key, priority and on-invalid.

    Named after Symfony's ``Definition::setDecoratedService``.

    Attributes:
        key: The ``(type, qualifier)`` of the decorated service.
        priority: The decoration's priority. Higher wraps first.
        on_invalid: Behavior when the target is not defined -
            :class:`~xtr_dependency_injection.decorator.as_decorator.OnInvalid`.
    """

    key: ServiceKey
    priority: int = 0
    on_invalid: OnInvalid = OnInvalid.EXCEPTION


@dataclass(slots=True)
class Definition:
    """One service as the builder knows it, before it is compiled for wireup.

    Attributes:
        key: The type and qualifier it is provided under.
        provider: The class, factory function or instance that builds it.
        kind: How ``provider`` is registered: ``"class"``, ``"factory"`` or
            ``"instance"``.
        lifetime: How long wireup keeps what it builds.
        origin: Who contributed it.
        priority: Its position in ordered collections; ``None`` means "no
            explicit priority", read as zero by todo 14's emission_order
            (Symfony's ``BeforeAfterSorter`` will consume it in todo 17).
        tags: Tag name → list of attribute mappings (Symfony's
            ``Definition::$tags``). ``kernel.reset`` is the Symfony 8.2 tag
            resettable services carry, read by the compiler.
        decorates: What service this definition decorates, when it does
            (Symfony's ``Definition::setDecoratedService``).
        before: Types this definition must precede in tagged collections
            (used by todo 17's ``BeforeAfterSorter``).
        after: Types this definition must follow in tagged collections.
    """

    key: ServiceKey
    provider: object
    kind: Literal["class", "factory", "instance"]
    lifetime: Lifetime
    origin: Origin
    priority: int | None = None
    tags: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    decorates: Decorates | None = None
    before: tuple[type, ...] = ()
    after: tuple[type, ...] = ()

    def add_tag(self, name: str, /, **attributes: object) -> Definition:
        """Add a tag ``name`` with the given attribute mapping.

        Named after Symfony's ``Definition::addTag``: repeatable — each call
        appends one attribute mapping under ``name``.
        """
        self.tags.setdefault(name, []).append(dict(attributes))
        return self

    def has_tag(self, name: str, /) -> bool:
        """Return whether the tag ``name`` was added at least once."""
        return name in self.tags

    def get_tag(self, name: str, /) -> list[dict[str, object]]:
        """Return every attribute mapping added under ``name``.

        Named after Symfony's ``Definition::getTag``. Returns an empty list
        when the tag was never added.
        """
        return list(self.tags.get(name, ()))

    def clear_tag(self, name: str, /) -> Definition:
        """Remove every attribute mapping added under ``name``."""
        _ = self.tags.pop(name, None)
        return self

    def set_decorated_service(
        self,
        target: type,
        /,
        *,
        qualifier: Hashable | None = None,
        priority: int = 0,
        on_invalid: OnInvalid = OnInvalid.EXCEPTION,
    ) -> Definition:
        """Mark this definition as decorating ``(target, qualifier)``.

        Named after Symfony's ``Definition::setDecoratedService``. ``on_invalid``
        chooses what happens when the target is not defined - see
        :class:`~xtr_dependency_injection.decorator.as_decorator.OnInvalid`.
        """
        self.decorates = Decorates(
            key=(target, qualifier), priority=priority, on_invalid=on_invalid
        )
        return self
