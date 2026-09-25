from __future__ import annotations

import pytest
from wireup import injectable

from tests.support.bundles import ChorusBundle, EchoBundle, EchoConfig
from xtr_dependency_injection.builder import Definition, Origin, ServiceKey
from xtr_dependency_injection.builder.service_configurator import (
    BuildState,
    DecorationRequest,
    ResettableRequest,
    ServiceConfigurator,
)
from xtr_dependency_injection.compiler.wireup_compiler import Decoration
from xtr_dependency_injection.config.config_resolver import resolve_configs
from xtr_dependency_injection.decorator.compiler_pass import compiler_pass
from xtr_dependency_injection.diagnostics.report import ReportBuilder
from xtr_dependency_injection.discovery import DiscoveredBundle
from xtr_dependency_injection.exception import (
    DecoratorSignatureError,
    InvalidEnvironmentError,
    ParameterConflictError,
    UnknownConfigTypeError,
    UnknownServiceError,
)
from xtr_dependency_injection.kernel.kernel import (
    Assembly,
    _autoconfigure,
    _compile,
    _configs,
    _declared,
    _early_scan,
    _environment,
    _finalize,
    _late_scan,
    _load,
    _merged,
    _process,
    definition_reports,
)
from xtr_dependency_injection.kernel.kernel_bundle import KernelBundle
from xtr_dependency_injection.scan.default_excludes import DEFAULT_EXCLUDES
from xtr_dependency_injection.scan.scanned_object import ScannedObject
from xtr_dependency_injection.scan.scanner import Scanner, ScanResult


class Service:
    pass


class NotADecorator:
    def __init__(self, service: Service) -> None:
        self.service: Service = service


@injectable
class Declared:
    pass


def _state(*bundles: str) -> BuildState:
    return BuildState(env="dev", debug=False, bundles=("kernel", *bundles), configs={})


def _scanned(obj: object, owner: str | None = None, order: int = 1) -> ScannedObject:
    return ScannedObject(obj, f"tests:{getattr(obj, '__qualname__', obj)}", owner, order)


def test_step_1_returns_the_environment_and_debug() -> None:
    assert _environment("dev", debug=True, allowed=None) == ("dev", True)


def test_step_1_refuses_a_disallowed_environment() -> None:
    with pytest.raises(InvalidEnvironmentError):
        _ = _environment("qa", debug=False, allowed=("dev",))


def test_step_3_scans_the_app_then_each_bundles_resources() -> None:
    scanner = Scanner(env="dev", exclude=DEFAULT_EXCLUDES)

    result = _early_scan(scanner, ["tests.fixtures.app_scan.alpha"], [KernelBundle()])

    assert [scanned.owner for scanned in result.services] == [None]


def test_step_4_names_the_inactive_bundle_owning_a_config_type() -> None:
    discovered = (DiscoveredBundle("echo", "x:EchoBundle", None, EchoBundle, None),)
    scanner = Scanner(env="dev", exclude=DEFAULT_EXCLUDES)
    early = scanner.scan(["tests.fixtures.app_kernel.configuration"], owner=None)

    with pytest.raises(UnknownConfigTypeError, match=r"its bundle 'echo' is not active"):
        _ = _configs([KernelBundle()], early, discovered, ["kernel"], "dev")


def test_step_5_loads_each_bundle_with_its_origin() -> None:
    state = _state("echo")
    configs = resolve_configs(
        bundles=[KernelBundle(), EchoBundle()], providers=[], inactive={}, env="dev"
    )

    _load(state, [KernelBundle(), EchoBundle()], configs)

    origins = {definition.origin for definition in state.store.definitions()}
    assert origins == {Origin("kernel", "kernel"), Origin("bundle", "echo")}


def test_step_6_scans_what_bundles_requested() -> None:
    state = _state("chorus")
    ServiceConfigurator(state, Origin("bundle", "chorus")).scan("tests.fixtures.app_kernel_late")

    result = _late_scan(Scanner(env="dev", exclude=DEFAULT_EXCLUDES), state)

    assert [scanned.owner for scanned in result.declared] == ["chorus"]


def test_step_7_gives_a_bundle_owned_declaration_the_bundle_origin() -> None:
    state = _state("chorus")

    _declared(state, [_scanned(Declared, owner="chorus")])

    definition = state.store.get((Declared, None))
    assert definition is not None
    assert definition.origin == Origin("bundle", "chorus", "declared by tests:Declared")


def test_step_7_gives_an_app_declaration_the_app_origin() -> None:
    state = _state()

    _declared(state, [_scanned(Declared)])

    definition = state.store.get((Declared, None))
    assert definition is not None
    assert (definition.origin, definition.kind) == (Origin("app", "tests:Declared"), "declared")


def test_step_8_notes_the_autoconfigured_candidate() -> None:
    state = _state("echo")

    def register(obj: object, _meta: object, services: ServiceConfigurator) -> None:
        if isinstance(obj, type):
            services.service(obj)

    ServiceConfigurator(state, Origin("bundle", "echo")).autoconfigure(lambda _o: (1,), register)

    _autoconfigure(state, [_scanned(Service)])

    definition = state.store.get((Service, None))
    assert definition is not None
    assert definition.origin == Origin("bundle", "echo", "via autoconfigure of tests:Service")


def test_step_9_runs_compiler_passes_by_priority_then_scan_order() -> None:
    ran: list[str] = []

    @compiler_pass
    def late(_builder: object) -> None:
        ran.append("late")

    @compiler_pass(priority=5)
    def early(_builder: object) -> None:
        ran.append("early")

    _process(_state(), [], [_scanned(late, order=1), _scanned(early, order=2)])

    assert ran == ["early", "late"]


def test_step_10_refuses_an_unknown_resettable() -> None:
    state = _state()
    state.resettables.append(ResettableRequest((Service, None), "reset"))

    with pytest.raises(UnknownServiceError, match="cannot resettable"):
        _ = _finalize(state, [])


def test_step_10_refuses_an_unknown_decoration_target() -> None:
    state = _state()
    state.decorations.append(DecorationRequest((Service, None), NotADecorator, 0, "x", 0))

    with pytest.raises(UnknownServiceError, match="cannot decorate"):
        _ = _finalize(state, [])


def test_step_10_refuses_a_decorator_without_inner() -> None:
    state = _state()
    ServiceConfigurator(state, Origin("app", "tests")).service(Service)
    state.decorations.append(DecorationRequest((Service, None), NotADecorator, 0, "x", 0))

    with pytest.raises(DecoratorSignatureError):
        _ = _finalize(state, [])


def test_step_10_marks_resettables_and_freezes() -> None:
    state = _state()
    ServiceConfigurator(state, Origin("app", "tests")).service(Service)
    state.resettables.append(ResettableRequest((Service, None), "clear"))

    _ = _finalize(state, [])

    definition = state.store.get((Service, None))
    assert definition is not None
    assert definition.reset_method == "clear"
    assert state.phase == "frozen"


def test_step_11_refuses_a_parameter_set_twice() -> None:
    state = _state()
    state.parameters.append(("bundle echo", {"app": {"punctuation": "?"}}))
    state.phase = "frozen"
    scanner = Scanner(env="dev", exclude=DEFAULT_EXCLUDES)
    providers = scanner.scan(["tests.fixtures.app_kernel.configuration"], owner=None).parameters

    with pytest.raises(ParameterConflictError):
        _ = _compile(
            Assembly(state, {}, list(providers), [], []),
            KernelBundle(),
            ReportBuilder(),
            bundles=[],
            concurrent_scoped_access=False,
        )


def test_step_11_reports_origin_overrides_and_decorators() -> None:
    state = _state("echo")
    ServiceConfigurator(state, Origin("bundle", "echo")).service(Service)
    ServiceConfigurator(state, Origin("app", "tests:Service")).service(Service, qualifier="x")
    state.store.add(
        Definition((Service, None), Service, "class", "singleton", Origin("app", "tests:Over"))
    )
    ordered = state.store.definitions()
    decorations: dict[ServiceKey, list[Decoration]] = {
        (Service, None): [Decoration(NotADecorator, "service", "tests:Wrapper")]
    }

    reports = definition_reports(state, ordered, decorations)

    report = next(r for r in reports if r.key == (Service, None))
    assert report.overrides == (Origin("bundle", "echo"),)
    assert report.decorated_by == ("tests:Wrapper",)
    assert report.provider_qualname == f"{__name__}.Service"


def test_merging_scan_results_keeps_every_queue_in_order() -> None:
    first = ScanResult(services=[_scanned(Service, order=1)])
    second = ScanResult(services=[_scanned(Declared, order=2)], declared=[_scanned(Declared)])

    merged = _merged([first, second])

    assert [s.obj for s in merged.services] == [Service, Declared]
    assert [s.obj for s in merged.declared] == [Declared]


def test_chorus_and_echo_resolve_in_dependency_order() -> None:
    configs = resolve_configs(
        bundles=[KernelBundle(), EchoBundle(), ChorusBundle()], providers=[], inactive={}, env="dev"
    )

    assert configs.values["echo"] == EchoConfig(channels=("chorus",))
