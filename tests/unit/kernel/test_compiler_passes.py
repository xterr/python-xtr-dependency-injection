from __future__ import annotations

from typing_extensions import override

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.pass_stage import PassStage
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.bundle import Bundle, as_bundle
from xtr_dependency_injection.decorator.compiler_pass import compiler_pass
from xtr_dependency_injection.decorator.remove_if_missing import (
    REMOVE_IF_MISSING_TAG,
    remove_if_missing,
)
from xtr_dependency_injection.kernel.kernel import (
    Kernel,
    _run_compiler_passes,
    collect_compiler_passes,
)
from xtr_dependency_injection.scan.scanned_object import ScannedObject


def _state(*bundles: str) -> BuildState:
    return BuildState(env="dev", debug=False, bundles=("kernel", *bundles), configs={})


def _scanned(obj: object, order: int = 1) -> ScannedObject:
    return ScannedObject(obj, f"tests:{getattr(obj, '__qualname__', obj)}", None, order)


def test_the_five_stages_are_ordered_early_to_late() -> None:
    assert [s.name for s in PassStage] == [
        "BEFORE_OPTIMIZATION",
        "OPTIMIZE",
        "BEFORE_REMOVING",
        "REMOVE",
        "AFTER_REMOVING",
    ]


def test_stages_run_before_optimization_before_optimize_before_removing() -> None:
    ran: list[str] = []

    @compiler_pass(stage=PassStage.AFTER_REMOVING, priority=99)
    def last(_builder: object) -> None:
        ran.append("after")

    @compiler_pass(stage=PassStage.BEFORE_REMOVING)
    def before_removing(_builder: object) -> None:
        ran.append("before_removing")

    @compiler_pass(stage=PassStage.OPTIMIZE)
    def optimize(_builder: object) -> None:
        ran.append("optimize")

    @compiler_pass(stage=PassStage.BEFORE_OPTIMIZATION)
    def early(_builder: object) -> None:
        ran.append("early")

    _run_compiler_passes(
        _state(),
        [],
        [
            _scanned(last, order=1),
            _scanned(before_removing, order=2),
            _scanned(optimize, order=3),
            _scanned(early, order=4),
        ],
        [],
    )

    assert ran == ["early", "optimize", "before_removing", "after"]


def test_priority_within_a_stage_runs_higher_first() -> None:
    ran: list[str] = []

    @compiler_pass(stage=PassStage.BEFORE_OPTIMIZATION, priority=1)
    def low(_builder: object) -> None:
        ran.append("low")

    @compiler_pass(stage=PassStage.BEFORE_OPTIMIZATION, priority=10)
    def high(_builder: object) -> None:
        ran.append("high")

    _run_compiler_passes(
        _state(),
        [],
        [_scanned(low, order=1), _scanned(high, order=2)],
        [],
    )

    assert ran[:2] == ["high", "low"]


def test_a_remove_stage_pass_sees_definitions_removed_by_before_removing() -> None:
    seen: dict[str, bool] = {}

    @remove_if_missing(class_="no_such_module_xyz_15:Missing")
    class Dropped:
        pass

    @compiler_pass(stage=PassStage.REMOVE)
    def check(builder: ContainerBuilder) -> None:
        seen["still_there"] = builder.has_definition(Dropped)

    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:Dropped"))
        .set(Dropped)
        .add_tag(REMOVE_IF_MISSING_TAG, class_="no_such_module_xyz_15:Missing")
    )

    _run_compiler_passes(state, [], [_scanned(check)], [])

    assert seen == {"still_there": False}


class _NoOverrideBundle(Bundle):
    pass


class _OverridingBundle(Bundle):
    ran: bool = False

    @override
    def process(self, builder: ContainerBuilder) -> None:
        del builder
        type(self).ran = True


@as_bundle("no_override")
class NoOverrideBundle(_NoOverrideBundle):
    pass


@as_bundle("overriding")
class OverridingBundle(_OverridingBundle):
    pass


def test_bundle_process_runs_only_when_the_class_overrides_it() -> None:
    OverridingBundle.ran = False
    state = _state("no_override", "overriding")

    _run_compiler_passes(state, [NoOverrideBundle(), OverridingBundle()], [], [])

    assert OverridingBundle.ran is True


def test_collect_records_the_built_in_kernel_passes_in_stage_order() -> None:
    collected = collect_compiler_passes(_state(), [], [], [])

    descriptions = [request.description for request in collected]
    assert descriptions == [
        "kernel:resolve_decorations",
        "kernel:remove_if_missing",
        "kernel:validate_aliases",
    ]
    stages = {request.description: request.stage for request in collected}
    assert stages["kernel:resolve_decorations"] == PassStage.OPTIMIZE
    assert stages["kernel:remove_if_missing"] == PassStage.BEFORE_REMOVING
    assert stages["kernel:validate_aliases"] == PassStage.AFTER_REMOVING


def test_add_compiler_pass_registers_a_pass_in_the_build_phase() -> None:
    state = _state()
    state.phase = "build"
    calls: list[str] = []

    def scanner_pass(_builder: ContainerBuilder) -> None:
        calls.append("build-added")

    ContainerBuilder(state, Origin("bundle", "scan")).add_compiler_pass(
        scanner_pass, stage=PassStage.AFTER_REMOVING, priority=7
    )

    assert len(state.compiler_passes) == 1
    request = state.compiler_passes[0]
    assert request.stage == PassStage.AFTER_REMOVING
    assert request.priority == 7
    assert request.description.endswith("scanner_pass")


def test_a_bundles_added_compiler_pass_is_collected_after_its_process() -> None:
    calls: list[str] = []

    def added(_builder: ContainerBuilder) -> None:
        calls.append("added")

    class _ProcessingBundle(Bundle):
        @override
        def build(self, builder: ContainerBuilder) -> None:
            builder.add_compiler_pass(added, stage=PassStage.BEFORE_OPTIMIZATION)

        @override
        def process(self, builder: ContainerBuilder) -> None:
            del builder
            calls.append("process")

    @as_bundle("processing")
    class ProcessingBundle(_ProcessingBundle):
        pass

    state = _state("processing")
    state.phase = "build"
    bundle = ProcessingBundle()
    bundle.build(ContainerBuilder(state, Origin("bundle", "processing")))

    _run_compiler_passes(state, [bundle], [], [])

    assert calls == ["process", "added"]


def test_a_remove_if_missing_definition_is_absent_from_a_built_container() -> None:
    @remove_if_missing(package="no-such-dist-xyz-15", class_="pkg:Cls")
    class Marked:
        pass

    class _RegisteringBundle(Bundle):
        @override
        def load_extension(
            self,
            config: object,
            services: ServiceConfigurator,
            builder: ContainerBuilder,
        ) -> None:
            del config, builder
            _ = services.set(Marked).add_tag(REMOVE_IF_MISSING_TAG, package="no-such-dist-xyz-15")

    @as_bundle("registering")
    class RegisteringBundle(_RegisteringBundle):
        pass

    kernel = Kernel(
        "tests.fixtures.app_kernel",
        bundles={RegisteringBundle: {"all": True}},
        resources=(),
        env="dev",
    )
    compiled = kernel.build()
    keys = {report.key for report in compiled.report.definitions}
    assert (Marked, None) not in keys
