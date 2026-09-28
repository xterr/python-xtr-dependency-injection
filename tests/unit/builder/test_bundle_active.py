from __future__ import annotations

from xtr_dependency_injection import bundle_active
from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState


def _builder(parameters: dict[str, object] | None = None) -> ContainerBuilder:
    state = BuildState(env="dev", debug=False, bundles=("kernel", "alpha"), configs={})
    state.phase = "process"
    if parameters is not None:
        state.parameter_bag.add(parameters)
    return ContainerBuilder(state, Origin("bundle", "alpha"))


def test_a_bundle_the_kernel_lists_as_active_is_active() -> None:
    builder = _builder({"kernel": {"bundles": {"logging": "xtr_logging.bundle:LoggingBundle"}}})

    assert bundle_active(builder, "logging")
    assert not bundle_active(builder, "cache")


def test_nothing_is_active_before_the_kernel_lists_its_bundles() -> None:
    assert not bundle_active(_builder(), "logging")
