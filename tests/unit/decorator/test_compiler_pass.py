from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from xtr_dependency_injection.compiler.pass_stage import PassStage
from xtr_dependency_injection.decorator.compiler_pass import (
    CompilerPassMarker,
    compiler_pass,
    compiler_pass_of,
)

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.compiler.compiler_pass_interface import CompilerPassInterface


def test_a_bare_compiler_pass_has_priority_zero_and_before_optimization_stage() -> None:
    @compiler_pass
    class Adjust:
        def process(self, builder: ContainerBuilder) -> None:
            del builder

    assert compiler_pass_of(Adjust) == CompilerPassMarker(0, PassStage.BEFORE_OPTIMIZATION)


def test_a_compiler_pass_records_its_priority() -> None:
    @compiler_pass(priority=5)
    class Adjust:
        def process(self, builder: ContainerBuilder) -> None:
            del builder

    assert compiler_pass_of(Adjust) == CompilerPassMarker(5, PassStage.BEFORE_OPTIMIZATION)


def test_a_compiler_pass_records_its_stage() -> None:
    @compiler_pass(stage=PassStage.AFTER_REMOVING)
    class Adjust:
        def process(self, builder: ContainerBuilder) -> None:
            del builder

    assert compiler_pass_of(Adjust) == CompilerPassMarker(0, PassStage.AFTER_REMOVING)


def test_an_unmarked_class_is_not_a_compiler_pass() -> None:
    class Adjust:
        def process(self, builder: ContainerBuilder) -> None:
            del builder

    assert compiler_pass_of(Adjust) is None


def test_a_function_is_refused() -> None:
    def adjust(_builder: object) -> None: ...

    with pytest.raises(TypeError, match="CompilerPassInterface"):
        _ = compiler_pass(cast("type[CompilerPassInterface]", adjust))


def test_a_class_without_process_is_refused() -> None:
    class NotAPass:
        pass

    with pytest.raises(TypeError, match="CompilerPassInterface"):
        _ = compiler_pass(cast("type[CompilerPassInterface]", NotAPass))
