from __future__ import annotations

import pytest

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.compiler.check_alias_validity_pass import validate_aliases_pass
from xtr_dependency_injection.exception import UnknownServiceError


class Alpha:
    pass


class Peer:
    pass


def _state(*bundles: str) -> BuildState:
    return BuildState(env="dev", debug=False, bundles=("kernel", *bundles), configs={})


def test_validate_aliases_raises_when_the_alias_target_is_missing() -> None:
    state = _state()
    ServiceConfigurator(state, Origin("app", "tests:Alpha")).alias(Alpha, Peer)

    with pytest.raises(UnknownServiceError, match="set_alias"):
        validate_aliases_pass(ContainerBuilder(state, Origin("kernel", "kernel")))
