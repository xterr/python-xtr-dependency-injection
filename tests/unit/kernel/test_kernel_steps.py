from __future__ import annotations

from dataclasses import replace

import pytest
from typing_extensions import override

from tests.support.bundles import EchoBundle, EchoConfig
from xtr_dependency_injection.builder import Definition, Origin, ServiceKey
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import (
    BuildState,
    Prepend,
    ServiceConfigurator,
)
from xtr_dependency_injection.bundle import Bundle, as_bundle
from xtr_dependency_injection.compiler.wireup_compiler import Decoration
from xtr_dependency_injection.config.config_resolver import resolve_configs
from xtr_dependency_injection.decorator.compiler_pass import compiler_pass
from xtr_dependency_injection.exception import (
    DecoratorSignatureError,
    InvalidEnvironmentError,
    ParameterConflictError,
    UnknownConfigTypeError,
    UnknownServiceError,
)
from xtr_dependency_injection.kernel.kernel import (
    Kernel,
    _autoconfigure,
    _check_environment,
    _configs,
    _early_scan,
    _late_scan,
    _load,
    _run_compiler_passes,
    definition_reports,
    resolve_decorations_pass,
    validate_aliases_pass,
)
from xtr_dependency_injection.kernel.kernel_bundle import KernelBundle
from xtr_dependency_injection.scan.default_excludes import DEFAULT_EXCLUDES
from xtr_dependency_injection.scan.scanned_object import ScannedObject
from xtr_dependency_injection.scan.scanner import Scanner


class Service:
    pass


class NotADecorator:
    def __init__(self, service: Service) -> None:
        self.service: Service = service


def _state(*bundles: str) -> BuildState:
    return BuildState(env="dev", debug=False, bundles=("kernel", *bundles), configs={})


def _scanned(obj: object, owner: str | None = None, order: int = 1) -> ScannedObject:
    return ScannedObject(obj, f"tests:{getattr(obj, '__qualname__', obj)}", owner, order)


def test_step_1_allows_an_allowed_environment() -> None:
    _check_environment("dev", allowed=None)


def test_step_1_refuses_a_disallowed_environment() -> None:
    with pytest.raises(InvalidEnvironmentError):
        _check_environment("qa", allowed=("dev",))


def test_step_3_scans_the_app_then_each_bundles_resources() -> None:
    scanner = Scanner(env="dev", exclude=DEFAULT_EXCLUDES)

    result = _early_scan(scanner, ["tests.fixtures.app_scan.alpha"], [KernelBundle()])

    assert [scanned.owner for scanned in result.services] == [None]


def test_step_4_names_the_inactive_bundle_owning_a_config_type() -> None:
    scanner = Scanner(env="dev", exclude=DEFAULT_EXCLUDES)
    early = scanner.scan(["tests.fixtures.app_kernel.configuration"], owner=None)

    with pytest.raises(UnknownConfigTypeError, match=r"its bundle 'echo' is not active"):
        _ = _configs([KernelBundle()], early, {EchoConfig: "echo"}, "dev")


def test_step_5_loads_each_bundle_with_its_origin() -> None:
    state = _state("echo")
    configs = resolve_configs(
        bundles=[KernelBundle(), EchoBundle()], providers=[], inactive={}, env="dev"
    )

    _load(state, [KernelBundle(), EchoBundle()], configs)

    origins = {definition.origin for definition in state.store.entries()}
    assert origins == {Origin("kernel", "kernel"), Origin("bundle", "echo")}


def test_step_6_scans_what_bundles_requested() -> None:
    state = _state("chorus")
    ServiceConfigurator(state, Origin("bundle", "chorus")).load("tests.fixtures.app_kernel_late")

    result = _late_scan(Scanner(env="dev", exclude=DEFAULT_EXCLUDES), state)

    assert [scanned.owner for scanned in result.marked] == ["chorus"]


def test_step_8_notes_the_autoconfigured_candidate() -> None:
    state = _state("echo")

    def register(obj: object, _meta: object, services: ServiceConfigurator) -> None:
        if isinstance(obj, type):
            _ = services.set(obj)

    state.phase = "load"
    ContainerBuilder(state, Origin("bundle", "echo")).register_attribute_for_autoconfiguration(
        lambda _o: (1,), register
    )

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

    _run_compiler_passes(_state(), [], [_scanned(late, order=1), _scanned(early, order=2)], [])

    assert ran[:2] == ["early", "late"]


def test_step_10_refuses_an_unknown_decoration_target() -> None:
    state = _state()
    origin = Origin("app", "tests:Wrapper")
    state.store.add(
        Definition(
            key=(NotADecorator, None),
            provider=NotADecorator,
            kind="class",
            lifetime="singleton",
            origin=origin,
        ).set_decorated_service(Service)
    )

    with pytest.raises(UnknownServiceError, match="cannot decorate"):
        resolve_decorations_pass(ContainerBuilder(state, Origin("kernel", "kernel")), [])


def test_step_10_refuses_a_decorator_without_autowire_decorated_parameter() -> None:
    state = _state()
    _ = ServiceConfigurator(state, Origin("app", "tests")).set(Service)
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:Wrapper"))
        .set(NotADecorator)
        .set_decorated_service(Service)
    )

    with pytest.raises(DecoratorSignatureError):
        resolve_decorations_pass(ContainerBuilder(state, Origin("kernel", "kernel")), [])


def test_step_10_freezes_the_builder() -> None:
    state = _state()
    _ = ServiceConfigurator(state, Origin("app", "tests")).set(Service)
    state.phase = "process"

    validate_aliases_pass(ContainerBuilder(state, Origin("kernel", "kernel")))

    assert state.phase == "frozen"


@as_bundle("param_a")
class ParamABundle(Bundle):
    @override
    def load_extension(
        self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config, services
        builder.set_parameter("app.punctuation", "?")


@as_bundle("param_b")
class ParamBBundle(Bundle):
    @override
    def load_extension(
        self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config, services
        builder.set_parameter("app.punctuation", "!")


def test_step_11_refuses_a_parameter_set_twice() -> None:
    kernel = Kernel(
        "tests.fixtures.app_kernel",
        bundles={ParamABundle: {"all": True}, ParamBBundle: {"all": True}},
        resources=(),
        env="dev",
    )

    with pytest.raises(ParameterConflictError):
        _ = kernel.build()


def test_step_11_reports_origin_overrides_and_decorators() -> None:
    state = _state("echo")
    _ = ServiceConfigurator(state, Origin("bundle", "echo")).set(Service)
    _ = ServiceConfigurator(state, Origin("app", "tests:Service")).set(Service, qualifier="x")
    state.store.add(
        Definition((Service, None), Service, "class", "singleton", Origin("app", "tests:Over"))
    )
    ordered = state.store.entries()
    decorations: dict[ServiceKey, list[Decoration]] = {
        (Service, None): [Decoration(NotADecorator, "service", "tests:Wrapper")]
    }

    reports = definition_reports(state, ordered, decorations)

    report = next(r for r in reports if r.key == (Service, None))
    assert report.overrides == (Origin("bundle", "echo"),)
    assert report.decorated_by == ("tests:Wrapper",)
    assert report.provider_qualname == f"{__name__}:Service"


def test_chorus_and_echo_resolve_in_dependency_order() -> None:
    def add_chorus(config: object) -> object:
        assert isinstance(config, EchoConfig)
        return replace(config, channels=(*config.channels, "chorus"))

    prepends = [
        Prepend(
            source="chorus",
            target=EchoConfig,
            fn=add_chorus,
            description="tests:add_chorus",
        ),
    ]
    configs = resolve_configs(
        bundles=[KernelBundle(), EchoBundle()],
        providers=[],
        inactive={},
        env="dev",
        prepends=prepends,
    )

    assert configs.values["echo"] == EchoConfig(channels=("chorus",))
