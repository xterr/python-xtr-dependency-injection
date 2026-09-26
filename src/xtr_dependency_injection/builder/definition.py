"""What the builder holds: one definition per service key, and where each came from."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
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

    Recorded by :meth:`Definition.set_decorated_service`.

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
            explicit priority", read as zero by :func:`emission_order` and
            consumed by :func:`sort_with_priorities`.
        tags: Tag name → list of attribute mappings. ``kernel.reset`` is the
            tag resettable services carry, read by the compiler.
        decorates: What service this definition decorates, when it does.
        before: Types this definition must precede in tagged collections
            (consumed by :func:`sort_with_priorities`).
        after: Types this definition must follow in tagged collections.
        arguments: Values for the provider's parameters, by name, given
            instead of injecting them. A value may hold an ``env()``
            placeholder or a ``%name%`` reference: it is resolved when the
            service is built.
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
    arguments: dict[str, object] = field(default_factory=dict)

    def set_argument(self, name: str, value: object, /) -> Definition:
        """Give the provider's parameter ``name`` the value ``value`` instead of injecting it.

        This is how a bundle hands its config to a service: the value stays
        on the definition, so an ``env()`` placeholder in it is resolved when
        the service is built, and the report shows it.
        """
        self.arguments[name] = value
        return self

    def set_arguments(self, arguments: Mapping[str, object], /) -> Definition:
        """Replace every argument by ``arguments``."""
        self.arguments = dict(arguments)
        return self

    def get_arguments(self) -> dict[str, object]:
        """Return the arguments, by parameter name."""
        return dict(self.arguments)

    def add_tag(self, name: str, /, **attributes: object) -> Definition:
        """Add a tag ``name`` with the given attribute mapping.

        Repeatable — each call appends one attribute mapping under ``name``.
        """
        self.tags.setdefault(name, []).append(dict(attributes))
        return self

    def has_tag(self, name: str, /) -> bool:
        """Return whether the tag ``name`` was added at least once."""
        return name in self.tags

    def get_tag(self, name: str, /) -> list[dict[str, object]]:
        """Return every attribute mapping added under ``name``.

        Returns an empty list when the tag was never added.
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

        ``on_invalid`` chooses what happens when the target is not defined - see
        :class:`~xtr_dependency_injection.decorator.as_decorator.OnInvalid`.
        """
        self.decorates = Decorates(
            key=(target, qualifier), priority=priority, on_invalid=on_invalid
        )
        return self
