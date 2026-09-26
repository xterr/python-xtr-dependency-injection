from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from xtr_dependency_injection.compiler.pass_config import PassConfig
from xtr_dependency_injection.compiler.pass_stage import PassStage

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.compiler.compiler_pass_interface import CompilerPassInterface


class Named:
    def __init__(self, name: str) -> None:
        self.name: str = name

    def process(self, builder: ContainerBuilder) -> None:
        del builder


def _names(passes: list[CompilerPassInterface]) -> list[str]:
    return [getattr(p, "name", type(p).__name__) for p in passes]


def test_the_five_stages_are_ordered_early_to_late() -> None:
    assert [s.name for s in PassStage] == [
        "BEFORE_OPTIMIZATION",
        "OPTIMIZE",
        "BEFORE_REMOVING",
        "REMOVE",
        "AFTER_REMOVING",
    ]


def test_the_built_in_passes_are_in_place() -> None:
    config = PassConfig()

    assert _names(config.get_before_optimization_passes()) == [
        "RegisterAutoconfigureAttributesPass",
        "AutowireAsDecoratorPass",
        "AttributeAutoconfigurationPass",
        "ResolveInstanceofConditionalsPass",
        "RegisterEnvVarProcessorsPass",
        "RemoveMissingDependenciesPass",
    ]
    assert _names(config.get_optimization_passes()) == [
        "ResolveParameterPlaceHoldersPass",
        "ValidateEnvPlaceholdersPass",
        "DecoratorServicePass",
        "CheckDefinitionValidityPass",
        "ResolveReferencesToAliasesPass",
    ]
    assert config.get_before_removing_passes() == []
    assert _names(config.get_removing_passes()) == ["ReplaceAliasByActualDefinitionPass"]
    assert config.get_after_removing_passes() == []
    assert config.get_merge_pass() is None


def test_a_pass_runs_by_priority_then_after_the_passes_already_at_its_priority() -> None:
    config = PassConfig()
    config.add_pass(Named("low"), PassStage.OPTIMIZE, -5)
    config.add_pass(Named("same"), PassStage.OPTIMIZE)
    config.add_pass(Named("high"), PassStage.OPTIMIZE, 5)

    assert _names(config.get_optimization_passes()) == [
        "high",
        "ResolveParameterPlaceHoldersPass",
        "ValidateEnvPlaceholdersPass",
        "DecoratorServicePass",
        "CheckDefinitionValidityPass",
        "ResolveReferencesToAliasesPass",
        "same",
        "low",
    ]


def test_the_merge_pass_runs_first_then_stage_by_stage() -> None:
    config = PassConfig()
    config.add_pass(Named("after"), PassStage.AFTER_REMOVING, 99)
    config.add_pass(Named("before"), PassStage.BEFORE_OPTIMIZATION, -99)
    config.set_merge_pass(Named("merge"))

    names = _names(config.get_passes())

    assert names[0] == "merge"
    assert names[-1] == "after"
    assert names.index("before") < names.index("DecoratorServicePass")


def test_a_pass_not_implementing_the_interface_is_refused() -> None:
    def adjust(_builder: object) -> None: ...

    with pytest.raises(TypeError, match="CompilerPassInterface"):
        PassConfig().add_pass(cast("CompilerPassInterface", adjust))
