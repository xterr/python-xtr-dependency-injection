from __future__ import annotations

from dataclasses import dataclass

import pytest

from xtr_dependency_injection.bundle import Bundle, BundleMetadata, NoConfig, as_bundle
from xtr_dependency_injection.exception import BundleDefinitionError


@dataclass(frozen=True)
class SampleConfig:
    level: int = 1


@dataclass(frozen=True)
class NeedsArguments:
    level: int


def test_every_argument_is_recorded() -> None:
    @as_bundle(
        "full",
        config=SampleConfig,
        requires=["alpha"],
        optional=["beta"],
        envs=["dev"],
        resources=["pkg.commands"],
    )
    class FullBundle(Bundle[SampleConfig]):
        pass

    assert FullBundle.metadata() == BundleMetadata(
        name="full",
        config=SampleConfig,
        requires=("alpha",),
        optional=("beta",),
        envs=("dev",),
        resources=("pkg.commands",),
    )


def test_no_config_type_means_no_config() -> None:
    @as_bundle("plain")
    class PlainBundle(Bundle):
        pass

    assert PlainBundle.metadata().config is NoConfig


@pytest.mark.parametrize("name", ["Upper", "1digit", "with-dash", "", "_under"])
def test_an_invalid_name_is_refused(name: str) -> None:
    with pytest.raises(BundleDefinitionError, match="lowercase letters"):
        _ = as_bundle(name)


def test_the_kernel_name_is_reserved() -> None:
    with pytest.raises(BundleDefinitionError, match="reserved"):
        _ = as_bundle("kernel")


def test_a_config_type_needing_arguments_is_refused() -> None:
    with pytest.raises(BundleDefinitionError, match="config type cannot be built"):
        _ = as_bundle("strict", config=NeedsArguments)


def test_a_class_that_is_not_a_bundle_is_refused() -> None:
    class NotABundle:
        pass

    with pytest.raises(BundleDefinitionError, match="is not a Bundle subclass"):
        # Deliberately the wrong type: the check exists for untyped callers.
        as_bundle("plain")(NotABundle)  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]


def test_a_bundle_requiring_constructor_arguments_is_refused() -> None:
    class Needy(Bundle):
        def __init__(self, dependency: object) -> None:
            self.dependency: object = dependency

    with pytest.raises(BundleDefinitionError, match="requires constructor arguments"):
        _ = as_bundle("needy")(Needy)
