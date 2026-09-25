from __future__ import annotations

from dataclasses import replace

from tests.support.bundles import EchoConfig
from xtr_dependency_injection.config.configure import configure
from xtr_dependency_injection.config.parameters import parameters
from xtr_dependency_injection.decorator.when import when


@configure
def shout(config: EchoConfig) -> EchoConfig:
    return replace(config, greeting=config.greeting.upper())


@configure
@when("prod")
def greet_prod(config: EchoConfig) -> EchoConfig:
    return replace(config, greeting=config.greeting + " prod")


@parameters
def app_parameters() -> dict[str, object]:
    return {"app": {"punctuation": "!"}}
