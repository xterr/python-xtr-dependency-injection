"""Refusing a set-aside class or function that an active bundle would register.

The scan sets aside a module needing a package that is not installed, and
nothing it defines becomes a candidate. A bundle registers an undecorated
class or function only through an autoconfigurator — the reader it gave
``ContainerBuilder.register_attribute_for_autoconfiguration`` finding
something on it — so this pass asks every reader about every set-aside object,
just before :class:`AttributeAutoconfigurationPass` asks them about the
candidates. One that finds something would have been registered: the build
fails rather than drop it.

The by-type rules of ``register_for_autoconfiguration`` are not asked: they
only add to a definition something else made, and nothing set aside has one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from xtr_dependency_injection.exception import SetAsideModuleUsedError

from ._state import state_of

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

__all__ = ["CheckSetAsideCandidatesPass"]


@final
class CheckSetAsideCandidatesPass:
    """Fails the build when an autoconfigurator would register a set-aside object."""

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Run every autoconfigurator's reader over every set-aside object.

        Raises:
            SetAsideModuleUsedError: If a reader finds something on one.
            Exception: Whatever a reader raised, with a note naming the
                reader and the object.
        """
        state = state_of(builder)
        for autoconfigurator in state.autoconfigurators:
            for scanned in state.set_aside:
                try:
                    found = tuple(autoconfigurator.reader(scanned.obj))
                except Exception as error:
                    reader = getattr(autoconfigurator.reader, "__qualname__", "reader")
                    where = f"of bundle {autoconfigurator.owner} on {scanned.name}"
                    note = (
                        f"raised by autoconfigure reader {reader} {where}, defined in a module "
                        "set aside because a package it needs is not installed"
                    )
                    error.add_note(note)
                    raise
                if not found:
                    continue
                module = scanned.name.partition(":")[0]
                report = state.set_aside_modules[module]
                raise SetAsideModuleUsedError(
                    scanned.name,
                    f"bundle {autoconfigurator.owner!r} would register it",
                    module=module,
                    missing=report.missing,
                    through=report.through,
                )
