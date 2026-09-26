from __future__ import annotations

from xtr_dependency_injection.builder import Definition, Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState
from xtr_dependency_injection.compiler.resolve_parameter_placeholders_pass import (
    ResolveParameterPlaceHoldersPass,
)
from xtr_dependency_injection.config import env


def test_every_source_and_the_bag_are_resolved_and_unescaped() -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.add_parameters(Origin("kernel", "kernel"), {"kernel": {"project_dir": "/srv"}})
    state.add_parameters(
        Origin("app", "tests"),
        {"app": {"log": "%kernel.project_dir%/log", "pct": "5%%", "port": "%env(int:PORT)%"}},
    )
    state.phase = "process"

    ResolveParameterPlaceHoldersPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))

    _, app = state.parameters[1]
    assert app == {"app": {"log": "/srv/log", "pct": "5%", "port": env("int:PORT")}}
    assert state.parameter_bag.get("app.log") == "/srv/log"
    assert state.parameter_bag.get("app.pct") == "5%"
    assert state.parameter_bag.is_resolved()


class Mailer:
    def __init__(self, spool: str, port: object) -> None:
        self.spool: str = spool
        self.port: object = port


def test_definition_arguments_are_resolved_and_unescaped() -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.add_parameters(Origin("kernel", "kernel"), {"kernel": {"project_dir": "/srv"}})
    definition = Definition((Mailer, None), Mailer, "class", "singleton", Origin("app", "tests"))
    state.store.add(
        definition.set_arguments({"spool": "%kernel.project_dir%/5%%", "port": "%env(int:PORT)%"})
    )
    state.phase = "process"

    ResolveParameterPlaceHoldersPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))

    assert definition.get_arguments() == {"spool": "/srv/5%", "port": env("int:PORT")}
