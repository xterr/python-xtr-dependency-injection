from __future__ import annotations

from typing import TYPE_CHECKING, final

from typing_extensions import override

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.cache_clearer import CacheClearerInterface, ChainCacheClearer
from xtr_dependency_injection.compiler.add_cache_clearer_pass import (
    CACHE_CLEARER_TAG,
    AddCacheClearerPass,
)
from xtr_dependency_injection.kernel.kernel_bundle import chain_cache_clearer

if TYPE_CHECKING:
    from pathlib import Path


@final
class LowClearer(CacheClearerInterface):
    @override
    async def clear(self, cache_dir: Path) -> None:
        del cache_dir


@final
class HighClearer(CacheClearerInterface):
    @override
    async def clear(self, cache_dir: Path) -> None:
        del cache_dir


def test_the_chain_gets_every_tagged_clearer_highest_priority_first() -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.phase = "load"
    kernel = ServiceConfigurator(state, Origin("kernel", "kernel"))
    _ = kernel.set(chain_cache_clearer).set_argument("clearer_names", [])
    app = ServiceConfigurator(state, Origin("app", "tests"))
    _ = app.set(LowClearer).add_tag(CACHE_CLEARER_TAG)
    _ = app.set(HighClearer).add_tag(CACHE_CLEARER_TAG, priority=10)
    state.phase = "process"

    AddCacheClearerPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))

    definition = state.store.get((ChainCacheClearer, None))
    assert definition is not None
    names = [f"{CACHE_CLEARER_TAG}.0", f"{CACHE_CLEARER_TAG}.1"]
    assert definition.arguments["clearer_names"] == names
    assert state.aliases[CacheClearerInterface, names[0]] == (HighClearer, None)
    assert state.aliases[CacheClearerInterface, names[1]] == (LowClearer, None)
