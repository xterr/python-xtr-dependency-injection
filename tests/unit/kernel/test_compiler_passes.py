from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import override

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.bundle import Bundle, as_bundle
from xtr_dependency_injection.compiler.check_alias_validity_pass import CheckAliasValidityPass
from xtr_dependency_injection.compiler.pass_stage import PassStage
from xtr_dependency_injection.compiler.resettable_service_pass import ResettableServicePass
from xtr_dependency_injection.decorator.compiler_pass import compiler_pass
from xtr_dependency_injection.decorator.remove_if_missing import (
    REMOVE_IF_MISSING_TAG,
    remove_if_missing,
)
from xtr_dependency_injection.kernel.kernel import (
    BUNDLE_PASS_PRIORITY,
    Kernel,
    _prepare_container,
)
from xtr_dependency_injection.kernel.kernel_bundle import KernelBundle
from xtr_dependency_injection.scan.scanned_object import ScannedObject

if TYPE_CHECKING:
    from xtr_dependency_injection.bundle.bundle import AnyBundle

RAN: list[str] = []


def _state(*bundles: str) -> BuildState:
    return BuildState(env="dev", debug=False, bundles=("kernel", *bundles), configs={})


def _scanned(obj: object, order: int = 1) -> ScannedObject:
    return ScannedObject(obj, f"tests:{getattr(obj, '__qualname__', obj)}", None, order)


def _compile(state: BuildState, bundles: list[AnyBundle], scanned: list[ScannedObject]) -> None:
    RAN.clear()
    _prepare_container(state, bundles, scanned)
    state.compiler.compile(state)


@compiler_pass(stage=PassStage.AFTER_REMOVING, priority=99)
class Last:
    def process(self, builder: ContainerBuilder) -> None:
        del builder
        RAN.append("after")


@compiler_pass(stage=PassStage.BEFORE_REMOVING)
class BeforeRemoving:
    def process(self, builder: ContainerBuilder) -> None:
        del builder
        RAN.append("before_removing")


@compiler_pass(stage=PassStage.OPTIMIZE)
class Optimize:
    def process(self, builder: ContainerBuilder) -> None:
        del builder
        RAN.append("optimize")


@compiler_pass
class Early:
    def process(self, builder: ContainerBuilder) -> None:
        del builder
        RAN.append("early")


@compiler_pass(priority=10)
class High:
    def process(self, builder: ContainerBuilder) -> None:
        del builder
        RAN.append("high")


def test_stages_run_before_optimization_before_optimize_before_removing() -> None:
    _compile(
        _state(),
        [],
        [_scanned(Last, 1), _scanned(BeforeRemoving, 2), _scanned(Optimize, 3), _scanned(Early, 4)],
    )

    assert RAN == ["early", "optimize", "before_removing", "after"]


def test_priority_within_a_stage_runs_higher_first_then_scan_order() -> None:
    _compile(_state(), [], [_scanned(Early, 1), _scanned(High, 2)])

    assert RAN == ["high", "early"]


@compiler_pass
class RecordsOrigin:
    def process(self, builder: ContainerBuilder) -> None:
        RAN.append(str(builder._origin))


def test_a_scanned_pass_runs_as_the_application() -> None:
    _compile(_state(), [], [_scanned(RecordsOrigin)])

    assert [f"app tests:{RecordsOrigin.__qualname__}"] == RAN


@remove_if_missing(class_="no_such_module_xyz_15:Missing")
class Dropped:
    pass


@compiler_pass
class SeesDropped:
    def process(self, builder: ContainerBuilder) -> None:
        RAN.append(f"still there: {builder.has_definition(Dropped)}")


def test_a_before_optimization_pass_sees_the_missing_dependencies_removed() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:Dropped"))
        .set(Dropped)
        .add_tag(REMOVE_IF_MISSING_TAG, class_="no_such_module_xyz_15:Missing")
    )

    _compile(state, [], [_scanned(SeesDropped)])

    assert RAN == ["still there: False"]


class _NoOverrideBundle(Bundle):
    pass


class _ProcessingBundle(Bundle):
    @override
    def build(self, builder: ContainerBuilder) -> None:
        builder.add_compiler_pass(High())

    @override
    def process(self, builder: ContainerBuilder) -> None:
        RAN.append(f"process as {builder._origin}")


@as_bundle("no_override")
class NoOverrideBundle(_NoOverrideBundle):
    pass


@as_bundle("processing")
class ProcessingBundle(_ProcessingBundle):
    pass


def test_a_bundle_is_a_compiler_pass_only_when_it_overrides_process() -> None:
    state = _state("no_override", "processing")
    no_override, processing = NoOverrideBundle(), ProcessingBundle()

    _prepare_container(state, [no_override, processing], [])

    passes = state.compiler.get_pass_config().get_before_optimization_passes()
    assert processing in passes
    assert no_override not in passes


def test_a_bundle_runs_as_itself_after_every_other_before_optimization_pass() -> None:
    _compile(_state("processing"), [ProcessingBundle()], [_scanned(Early)])

    assert RAN == ["high", "early", "process as bundle processing"]
    assert BUNDLE_PASS_PRIORITY == -10000


def test_add_compiler_pass_registers_a_pass_in_the_build_phase() -> None:
    state = _state()
    state.phase = "build"

    ContainerBuilder(state, Origin("bundle", "scan")).add_compiler_pass(
        Early(), stage=PassStage.AFTER_REMOVING, priority=7
    )

    (added,) = state.compiler.get_pass_config().get_after_removing_passes()
    assert isinstance(added, Early)


def test_the_kernel_bundle_registers_its_passes() -> None:
    state = _state()

    _prepare_container(state, [KernelBundle()], [])

    config = state.compiler.get_pass_config()
    assert any(
        isinstance(p, ResettableServicePass) for p in config.get_before_optimization_passes()
    )
    assert any(isinstance(p, CheckAliasValidityPass) for p in config.get_before_removing_passes())


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
