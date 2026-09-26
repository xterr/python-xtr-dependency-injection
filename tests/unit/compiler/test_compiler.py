from __future__ import annotations

from typing import TYPE_CHECKING

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.service_configurator import BuildState
from xtr_dependency_injection.compiler.pass_stage import PassStage

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder


class Recording:
    def __init__(self, seen: list[tuple[str, str]]) -> None:
        self.seen: list[tuple[str, str]] = seen

    def process(self, builder: ContainerBuilder) -> None:
        origin = builder._origin
        self.seen.append((origin.kind, origin.name))


class Logging:
    def process(self, builder: ContainerBuilder) -> None:
        builder.log(self, "first\nsecond")


def _state() -> BuildState:
    return BuildState(env="dev", debug=False, bundles=("kernel",), configs={})


def test_each_pass_runs_as_its_origin_the_kernel_by_default() -> None:
    seen: list[tuple[str, str]] = []
    state = _state()
    state.compiler.add_pass(Recording(seen), PassStage.AFTER_REMOVING)
    state.compiler.add_pass(
        Recording(seen), PassStage.AFTER_REMOVING, origin=Origin("bundle", "beta")
    )

    state.compiler.compile(state)

    assert seen == [("kernel", "kernel"), ("bundle", "beta")]


def test_compiling_freezes_the_build_state() -> None:
    state = _state()

    state.compiler.compile(state)

    assert state.phase == "frozen"


def test_every_logged_line_names_its_pass() -> None:
    state = _state()
    state.compiler.add_pass(Logging())

    state.compiler.compile(state)

    prefix = f"{__name__}:Logging: "
    assert state.compiler.get_log() == [f"{prefix}first\n{prefix}second"]
