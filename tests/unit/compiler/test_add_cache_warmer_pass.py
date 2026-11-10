from __future__ import annotations

from typing import TYPE_CHECKING, final

import pytest
from typing_extensions import override

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.cache_warmer import CacheWarmerAggregate, CacheWarmerInterface
from xtr_dependency_injection.compiler.add_cache_warmer_pass import (
    CACHE_WARMER_TAG,
    AddCacheWarmerPass,
)
from xtr_dependency_injection.exception import InvalidDefinitionError
from xtr_dependency_injection.kernel.kernel_bundle import cache_warmer_aggregate

if TYPE_CHECKING:
    from pathlib import Path


@final
class LowWarmer(CacheWarmerInterface):
    @override
    async def warm_up(self, cache_dir: Path, build_dir: Path | None = None) -> None:
        del cache_dir, build_dir

    @override
    def is_optional(self) -> bool:
        return False


@final
class HighWarmer(CacheWarmerInterface):
    @override
    async def warm_up(self, cache_dir: Path, build_dir: Path | None = None) -> None:
        del cache_dir, build_dir

    @override
    def is_optional(self) -> bool:
        return False


def _state() -> BuildState:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.phase = "load"
    _ = (
        ServiceConfigurator(state, Origin("kernel", "kernel"))
        .set(cache_warmer_aggregate)
        .set_argument("warmer_names", [])
    )
    state.phase = "process"
    return state


def _app(state: BuildState) -> ServiceConfigurator:
    return ServiceConfigurator(state, Origin("app", "tests"))


def _process(state: BuildState) -> object:
    AddCacheWarmerPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))
    definition = state.store.get((CacheWarmerAggregate, None))
    assert definition is not None
    return definition.arguments["warmer_names"]


_FIRST = f"{CACHE_WARMER_TAG}.0"
_SECOND = f"{CACHE_WARMER_TAG}.1"


def test_the_aggregate_gets_every_tagged_warmer_highest_priority_first() -> None:
    state = _state()
    _ = _app(state).set(LowWarmer).add_tag(CACHE_WARMER_TAG)
    _ = _app(state).set(HighWarmer).add_tag(CACHE_WARMER_TAG, priority=10)

    names = _process(state)

    assert names == [_FIRST, _SECOND]
    assert state.aliases[CacheWarmerInterface, _FIRST] == (HighWarmer, None)
    assert state.aliases[CacheWarmerInterface, _SECOND] == (LowWarmer, None)


def test_equal_priorities_keep_definition_order() -> None:
    state = _state()
    _ = _app(state).set(LowWarmer).add_tag(CACHE_WARMER_TAG)
    _ = _app(state).set(HighWarmer).add_tag(CACHE_WARMER_TAG)

    _ = _process(state)

    assert state.aliases[CacheWarmerInterface, _FIRST] == (LowWarmer, None)


def test_the_aggregate_is_empty_without_tagged_warmers() -> None:
    assert _process(_state()) == []


def test_a_priority_that_is_not_an_integer_fails_the_build() -> None:
    state = _state()
    _ = _app(state).set(LowWarmer).add_tag(CACHE_WARMER_TAG, priority="high")

    with pytest.raises(InvalidDefinitionError, match="not an integer"):
        _ = _process(state)
