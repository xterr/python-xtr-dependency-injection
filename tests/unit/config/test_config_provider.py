from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from xtr_dependency_injection.bundle import NoConfig
from xtr_dependency_injection.config.config_provider import config_provider_of
from xtr_dependency_injection.config.configure import configure
from xtr_dependency_injection.decorator.when import when, when_not
from xtr_dependency_injection.exception import ConfigProviderError


@dataclass(frozen=True)
class SampleConfig:
    level: int = 0

    def __post_init__(self) -> None:
        if self.level < 0:
            raise ValueError("level must not be negative")


@dataclass(frozen=True)
class OtherConfig:
    pass


@configure
def base() -> SampleConfig:
    return SampleConfig(1)


@configure(priority=2)
def transform(config: SampleConfig) -> SampleConfig:
    return replace(config, level=config.level + 1)


def test_a_function_taking_nothing_is_a_base_provider() -> None:
    provider = config_provider_of(base)

    assert (provider.form, provider.config_type, provider.priority) == ("base", SampleConfig, 0)
    assert provider.name == f"{__name__}:base"


def test_a_function_taking_its_config_is_a_transform() -> None:
    provider = config_provider_of(transform)

    assert (provider.form, provider.priority) == ("transform", 2)


def test_a_base_provider_replaces_the_current_value() -> None:
    assert config_provider_of(base).apply(SampleConfig(9)) == SampleConfig(1)


def test_a_transform_receives_the_current_value() -> None:
    assert config_provider_of(transform).apply(SampleConfig(9)) == SampleConfig(10)


def test_an_unconditional_provider_is_not_conditional() -> None:
    assert not config_provider_of(base).conditional


def test_when_makes_a_provider_conditional() -> None:
    @configure
    @when("prod")
    def provide() -> SampleConfig:
        return SampleConfig()

    assert config_provider_of(provide).conditional


def test_when_not_makes_a_provider_conditional() -> None:
    @configure
    @when_not("prod")
    def provide() -> SampleConfig:
        return SampleConfig()

    assert config_provider_of(provide).conditional


def test_an_unmarked_function_is_refused() -> None:
    def provide() -> SampleConfig:
        return SampleConfig()

    with pytest.raises(ConfigProviderError, match="not decorated with @configure"):
        _ = config_provider_of(provide)


def test_a_missing_return_type_is_refused() -> None:
    @configure
    def provide():  # noqa: ANN202
        return SampleConfig()

    with pytest.raises(ConfigProviderError, match="return annotation"):
        _ = config_provider_of(provide)


def test_a_transform_of_another_type_is_refused() -> None:
    @configure
    def provide(_config: OtherConfig) -> SampleConfig:
        return SampleConfig()

    with pytest.raises(ConfigProviderError, match="must take the type it returns"):
        _ = config_provider_of(provide)


def test_two_parameters_are_refused() -> None:
    @configure
    def provide(config: SampleConfig, _extra: int) -> SampleConfig:
        return config

    with pytest.raises(ConfigProviderError, match="takes nothing"):
        _ = config_provider_of(provide)


def test_no_config_is_never_configurable() -> None:
    @configure
    def provide() -> NoConfig:
        return NoConfig()

    with pytest.raises(ConfigProviderError, match="NoConfig is never configurable"):
        _ = config_provider_of(provide)


def test_an_annotation_hidden_from_runtime_names_the_provider() -> None:
    @configure
    def provide() -> SampleConfig:
        return SampleConfig()

    provide.__annotations__ = {"return": "Undefined"}

    with pytest.raises(NameError) as caught:
        _ = config_provider_of(provide)

    assert any("not under TYPE_CHECKING" in note for note in caught.value.__notes__)


def test_a_returned_value_of_the_wrong_type_is_refused() -> None:
    @configure
    def provide() -> SampleConfig:
        return OtherConfig()  # pyright: ignore[reportReturnType]  # ty: ignore[invalid-return-type]

    with pytest.raises(ConfigProviderError, match="returned OtherConfig"):
        _ = config_provider_of(provide).apply(SampleConfig())


def test_a_validation_error_names_the_provider() -> None:
    @configure
    def provide() -> SampleConfig:
        return SampleConfig(-1)

    with pytest.raises(ValueError, match="negative") as caught:
        _ = config_provider_of(provide).apply(SampleConfig())

    assert caught.value.__notes__ == [
        f"raised by config provider {__name__}:{provide.__qualname__}"
    ]
