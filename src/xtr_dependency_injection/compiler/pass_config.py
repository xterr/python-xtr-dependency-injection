"""Which compiler passes run, in which order — with the built-in ones already in place.

The merge pass runs first; then the five :class:`PassStage` stages in order.
Within a stage passes run by priority, highest first, and in registration
order within one priority — so a built-in pass runs before a pass added later
at its priority. The defaults, by stage and priority:

- ``BEFORE_OPTIMIZATION`` 100: :class:`RegisterAutoconfigureAttributesPass`,
  :class:`AutowireAsDecoratorPass`, :class:`AttributeAutoconfigurationPass`,
  :class:`ResolveInstanceofConditionalsPass`,
  :class:`RegisterEnvVarProcessorsPass`,
  :class:`RemoveMissingDependenciesPass`;
- ``OPTIMIZE`` 0: :class:`ResolveParameterPlaceHoldersPass`,
  :class:`ValidateEnvPlaceholdersPass`, :class:`DecoratorServicePass`,
  :class:`CheckDefinitionValidityPass`,
  :class:`ResolveReferencesToAliasesPass`;
- ``REMOVE`` 0: :class:`ReplaceAliasByActualDefinitionPass`.

The kernel adds the rest: every bundle overriding ``process`` at
``BEFORE_OPTIMIZATION`` -10000, and the kernel bundle's
:class:`ResettableServicePass` (``BEFORE_OPTIMIZATION`` -32) and
:class:`CheckAliasValidityPass` (``BEFORE_REMOVING`` 0).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from .attribute_autoconfiguration_pass import AttributeAutoconfigurationPass
from .autowire_as_decorator_pass import AutowireAsDecoratorPass
from .check_definition_validity_pass import CheckDefinitionValidityPass
from .compiler_pass_interface import CompilerPassInterface
from .decorator_service_pass import DecoratorServicePass
from .pass_stage import PassStage
from .register_autoconfigure_attributes_pass import RegisterAutoconfigureAttributesPass
from .register_env_var_processors_pass import RegisterEnvVarProcessorsPass
from .remove_missing_dependencies_pass import RemoveMissingDependenciesPass
from .replace_alias_by_actual_definition_pass import ReplaceAliasByActualDefinitionPass
from .resolve_instanceof_conditionals_pass import ResolveInstanceofConditionalsPass
from .resolve_parameter_placeholders_pass import ResolveParameterPlaceHoldersPass
from .resolve_references_to_aliases_pass import ResolveReferencesToAliasesPass
from .validate_env_placeholders_pass import ValidateEnvPlaceholdersPass

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["PassConfig"]


@final
class PassConfig:
    """The passes of one compilation, bucketed by stage and priority."""

    __slots__ = ("_merge_pass", "_passes")

    def __init__(self) -> None:
        """Start with the built-in passes and no merge pass."""
        self._merge_pass: CompilerPassInterface | None = None
        self._passes: dict[PassStage, dict[int, list[CompilerPassInterface]]] = {
            stage: {} for stage in PassStage
        }
        self._passes[PassStage.BEFORE_OPTIMIZATION][100] = [
            RegisterAutoconfigureAttributesPass(),
            AutowireAsDecoratorPass(),
            AttributeAutoconfigurationPass(),
            ResolveInstanceofConditionalsPass(),
            RegisterEnvVarProcessorsPass(),
            RemoveMissingDependenciesPass(),
        ]
        self._passes[PassStage.OPTIMIZE][0] = [
            ResolveParameterPlaceHoldersPass(),
            ValidateEnvPlaceholdersPass(),
            DecoratorServicePass(),
            CheckDefinitionValidityPass(),
            ResolveReferencesToAliasesPass(),
        ]
        self._passes[PassStage.REMOVE][0] = [ReplaceAliasByActualDefinitionPass()]

    def get_passes(self) -> list[CompilerPassInterface]:
        """Return every pass in the order it runs: the merge pass, then stage by stage."""
        merge = [self._merge_pass] if self._merge_pass is not None else []
        return [*merge, *(p for stage in PassStage for p in _sorted(self._passes[stage]))]

    def add_pass(
        self,
        compiler_pass: CompilerPassInterface,
        stage: PassStage = PassStage.BEFORE_OPTIMIZATION,
        priority: int = 0,
    ) -> None:
        """Add ``compiler_pass`` to ``stage`` at ``priority``, after the passes already there.

        Raises:
            TypeError: If ``compiler_pass`` does not implement
                :class:`CompilerPassInterface`.
        """
        if not isinstance(compiler_pass, CompilerPassInterface):  # pyright: ignore[reportUnnecessaryIsInstance] — callers outside the type checker.
            msg = f"{compiler_pass!r} does not implement CompilerPassInterface"  # pyright: ignore[reportUnreachable]
            raise TypeError(msg)
        self._passes[stage].setdefault(priority, []).append(compiler_pass)

    def get_before_optimization_passes(self) -> list[CompilerPassInterface]:
        """Return the ``BEFORE_OPTIMIZATION`` passes in the order they run."""
        return _sorted(self._passes[PassStage.BEFORE_OPTIMIZATION])

    def get_optimization_passes(self) -> list[CompilerPassInterface]:
        """Return the ``OPTIMIZE`` passes in the order they run."""
        return _sorted(self._passes[PassStage.OPTIMIZE])

    def get_before_removing_passes(self) -> list[CompilerPassInterface]:
        """Return the ``BEFORE_REMOVING`` passes in the order they run."""
        return _sorted(self._passes[PassStage.BEFORE_REMOVING])

    def get_removing_passes(self) -> list[CompilerPassInterface]:
        """Return the ``REMOVE`` passes in the order they run."""
        return _sorted(self._passes[PassStage.REMOVE])

    def get_after_removing_passes(self) -> list[CompilerPassInterface]:
        """Return the ``AFTER_REMOVING`` passes in the order they run."""
        return _sorted(self._passes[PassStage.AFTER_REMOVING])

    def get_merge_pass(self) -> CompilerPassInterface | None:
        """Return the pass that loads the bundles' extensions, run before every stage."""
        return self._merge_pass

    def set_merge_pass(self, compiler_pass: CompilerPassInterface) -> None:
        """Set the pass that loads the bundles' extensions."""
        self._merge_pass = compiler_pass


def _sorted(passes: Mapping[int, list[CompilerPassInterface]]) -> list[CompilerPassInterface]:
    """Flatten priority buckets, highest priority first, each in registration order."""
    return [p for priority in sorted(passes, reverse=True) for p in passes[priority]]
