from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from xtr_dependency_injection.builder import Definition, Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState
from xtr_dependency_injection.compiler.validate_env_placeholders_pass import (
    ValidateEnvPlaceholdersPass,
)
from xtr_dependency_injection.config import env
from xtr_dependency_injection.exception import EnvPlaceholderError
from xtr_dependency_injection.runtime.env_var_processor import EnvVarProcessor

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class Config:
    value: object = None


def _process(config: object = None, parameters: dict[str, object] | None = None) -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={"x": config})
    state.parameter_bag.set_provided_types(EnvVarProcessor.get_provided_types())
    if parameters is not None:
        state.add_parameters(Origin("app", "tests"), parameters)
    state.phase = "process"
    ValidateEnvPlaceholdersPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))


def test_known_prefixes_and_arguments_pass() -> None:
    _process(
        Config([env("int:PORT"), env("key:host:json:DSN"), env("default:app.x:int:PORT")]),
        {"app": {"url": f"http://{env('HOST')}:{env('PORT', int)}"}},
    )


def test_an_unknown_prefix_is_refused() -> None:
    with pytest.raises(EnvPlaceholderError, match="unsupported env var prefix 'itn'"):
        _process(Config(env("itn:PORT")))


def test_an_unknown_prefix_in_a_parameter_is_refused() -> None:
    with pytest.raises(EnvPlaceholderError, match="'jsn'"):
        _process(parameters={"app": {"x": env("jsn:X")}})


@pytest.mark.parametrize(
    "embedded",
    [
        lambda: f"x{env('json:X')}",
        lambda: f"x{env('PATH', str.split)}",
        lambda: f"x{env('enum:a.B:X')}",
        lambda: f"x{env('shuffle:csv:X')}",
    ],
    ids=["array", "callable", "enum", "shuffle"],
)
def test_a_placeholder_that_is_no_scalar_cannot_be_embedded(
    embedded: Callable[[], object],
) -> None:
    value = embedded()

    with pytest.raises(EnvPlaceholderError, match="embedded in a string"):
        _process(Config(value))


@pytest.mark.parametrize(
    "expression",
    ["const:a.NAME", "default:app.x:HOST", "key:host:json:DSN"],
    ids=["const", "default", "key"],
)
def test_a_prefix_that_may_produce_a_scalar_can_be_embedded(expression: str) -> None:
    # Whether the value really is a scalar is only knowable once it is read;
    # resolution refuses it then, naming what it turned out to be.
    _process(Config(f"x{env(expression)}"))


def test_an_unknown_prefix_in_a_definition_argument_is_refused() -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.parameter_bag.set_provided_types(EnvVarProcessor.get_provided_types())
    definition = Definition((Config, None), Config, "class", "singleton", Origin("app", "tests"))
    state.store.add(definition.set_argument("value", env("jsno:X")))
    state.phase = "process"

    with pytest.raises(EnvPlaceholderError, match="'jsno'"):
        ValidateEnvPlaceholdersPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))
