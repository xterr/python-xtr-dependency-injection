from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typing_extensions import override

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.compiler.register_env_var_processors_pass import (
    ENV_VAR_PROCESSOR_TAG,
    RegisterEnvVarProcessorsPass,
)
from xtr_dependency_injection.exception import InvalidDefinitionError
from xtr_dependency_injection.runtime.env_var_processor import EnvVarProcessor
from xtr_dependency_injection.runtime.env_var_processor_interface import (
    EnvVarProcessorInterface,
)
from xtr_dependency_injection.runtime.env_var_processors_locator import EnvVarProcessorsLocator

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


class Upper(EnvVarProcessorInterface):
    @override
    def get_env(self, prefix: str, name: str, get_env: Callable[[str], object]) -> object:
        return str(get_env(name)).upper()

    @override
    @classmethod
    def get_provided_types(cls) -> Mapping[str, str]:
        return {"upper": "string", "int": "int"}


class Weird(Upper):
    @override
    @classmethod
    def get_provided_types(cls) -> Mapping[str, str]:
        return {"weird": "complex"}


class NotAProcessor:
    pass


def _process(*tagged: type) -> BuildState:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.phase = "process"
    services = ServiceConfigurator(state, Origin("app", "tests"))
    for cls in tagged:
        _ = services.set(cls).add_tag(ENV_VAR_PROCESSOR_TAG)
    RegisterEnvVarProcessorsPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))
    return state


def test_it_defines_the_built_in_processor_and_the_locator() -> None:
    state = _process()

    processor = state.store.get((EnvVarProcessor, None))
    assert processor is not None
    assert processor.get_tag("kernel.reset") == [{"method": "reset"}]
    assert state.store.get((EnvVarProcessorsLocator, None)) is not None
    assert state.parameter_bag.get_provided_types() == dict(EnvVarProcessor.get_provided_types())


def test_a_tagged_processor_adds_and_replaces_prefixes() -> None:
    types = _process(Upper).parameter_bag.get_provided_types()

    assert types["upper"] == "string"
    assert types["int"] == "int"
    assert "json" in types


def test_a_tagged_service_must_be_a_processor() -> None:
    with pytest.raises(InvalidDefinitionError, match="does not implement"):
        _ = _process(NotAProcessor)


def test_a_processor_must_name_known_types() -> None:
    with pytest.raises(InvalidDefinitionError, match="'complex'"):
        _ = _process(Weird)
