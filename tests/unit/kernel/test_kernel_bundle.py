from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import cast, final

import pytest
from typing_extensions import override

from tests.support.bundles import EchoBundle, EchoConfig
from xtr_dependency_injection import Bundle, as_bundle
from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.bundle import NoConfig
from xtr_dependency_injection.cache_clearer import CacheClearerInterface, ChainCacheClearer
from xtr_dependency_injection.cache_warmer import CacheWarmerAggregate, CacheWarmerInterface
from xtr_dependency_injection.kernel import KernelInterface
from xtr_dependency_injection.kernel.kernel import Kernel
from xtr_dependency_injection.kernel.kernel_bundle import KernelBundle
from xtr_dependency_injection.runtime.services_resetter import ServicesResetter


def _loaded() -> BuildState:
    bundle = KernelBundle()
    state = BuildState(env="dev", debug=True, bundles=("kernel",), configs={})
    state.phase = "load"
    origin = Origin("kernel", "kernel")
    bundle.load_extension(
        NoConfig(), ServiceConfigurator(state, origin), ContainerBuilder(state, origin)
    )
    return state


def test_the_kernel_bundle_is_named_kernel() -> None:
    assert KernelBundle.metadata().name == "kernel"


def test_it_provides_the_kernel_and_the_resetter() -> None:
    state = _loaded()

    # KernelInterface is registered as an alias to the concrete _KernelInfo.
    assert (KernelInterface, None) in state.aliases
    assert state.store.get((ServicesResetter, None)) is not None


@pytest.mark.anyio
async def test_the_kernel_registers_every_config_but_no_config() -> None:
    compiled = Kernel(
        "tests.fixtures.app_kernel",
        bundles={EchoBundle: {"all": True}},
        resources=(),
        env="dev",
    ).build()

    assert isinstance(await compiled.container.get(EchoConfig), EchoConfig)
    registered = {definition.key[0] for definition in compiled.report.definitions}
    assert NoConfig not in registered


def test_the_kernel_registers_the_kernel_parameters() -> None:
    compiled = Kernel(
        "tests.fixtures.app_kernel",
        bundles={EchoBundle: {"all": True}},
        resources=(),
        env="dev",
        name="shop",
    ).build()

    assert compiled.container.get_parameter("kernel.name") == "shop"
    assert compiled.container.get_parameter("kernel.environment") == "dev"
    bundles_param = compiled.container.get_parameter("kernel.bundles")
    assert isinstance(bundles_param, dict)
    keys = cast("dict[object, object]", bundles_param).keys()
    assert "kernel" in keys
    assert "echo" in keys


@final
class Log:
    def __init__(self) -> None:
        self.entries: list[str] = []


@final
class RoutesWarmer(CacheWarmerInterface):
    def __init__(self, log: Log) -> None:
        self._log = log

    @override
    async def warm_up(self, cache_dir: Path, build_dir: Path | None = None) -> None:
        built = None if build_dir is None else build_dir.name
        self._log.entries.append(f"routes {cache_dir.name} {built}")

    @override
    def is_optional(self) -> bool:
        return False


@final
class TemplatesWarmer(CacheWarmerInterface):
    def __init__(self, log: Log) -> None:
        self._log = log

    @override
    async def warm_up(self, cache_dir: Path, build_dir: Path | None = None) -> None:
        self._log.entries.append("templates")

    @override
    def is_optional(self) -> bool:
        return True


@final
class RemoteClearer(CacheClearerInterface):
    def __init__(self, log: Log) -> None:
        self._log = log

    @override
    async def clear(self, cache_dir: Path) -> None:
        self._log.entries.append(f"clear {cache_dir.name}")


@as_bundle("warming")
class WarmingBundle(Bundle):
    @override
    def load_extension(
        self, config: NoConfig, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config, builder
        _ = services.set(Log)
        _ = services.set(RoutesWarmer)
        _ = services.set(TemplatesWarmer)
        _ = services.set(RemoteClearer)


def _kernel(project_dir: Path, *, warming: bool = True) -> Kernel:
    """A kernel whose project is ``project_dir``, so its cache never lands in the checkout."""
    _ = (project_dir / "pyproject.toml").write_text("")
    package = ModuleType("warming_app")
    package.__file__ = str(project_dir / "warming_app" / "__init__.py")
    bundles: dict[type[Bundle], dict[str, bool]] = {WarmingBundle: {"all": True}} if warming else {}
    return Kernel(package, env="test", bundles=bundles, resources=())


async def _boot_log(project_dir: Path) -> list[str]:
    async with await _kernel(project_dir).boot() as booted:
        return (await booted.container.get(Log)).entries


@pytest.mark.anyio
async def test_a_warmer_and_a_clearer_are_collected_by_their_interface_alone(
    tmp_path: Path,
) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        log = await booted.container.get(Log)
        log.entries.clear()
        aggregate = await booted.container.get(CacheWarmerAggregate)
        aggregate.enable_optional_warmers()
        await aggregate.warm_up(Path("/cache"))
        await (await booted.container.get(ChainCacheClearer)).clear(Path("/cache"))

    assert log.entries == ["routes cache None", "templates", "clear cache"]


@pytest.mark.anyio
async def test_booting_with_a_cold_cache_runs_the_warmers_that_are_not_optional(
    tmp_path: Path,
) -> None:
    log = await _boot_log(tmp_path)

    assert log == ["routes test test"]
    assert (tmp_path / "var" / "cache" / "test" / ".warmed").is_file()


@pytest.mark.anyio
async def test_booting_with_a_warm_cache_runs_no_warmer(tmp_path: Path) -> None:
    _ = await _boot_log(tmp_path)

    assert await _boot_log(tmp_path) == []


@pytest.mark.anyio
async def test_a_cache_warmed_for_another_build_is_warmed_again(tmp_path: Path) -> None:
    _ = await _boot_log(tmp_path)
    _ = (tmp_path / "var" / "cache" / "test" / ".warmed").write_text("another build\n")

    assert await _boot_log(tmp_path) == ["routes test test"]


@pytest.mark.anyio
async def test_without_warmers_or_clearers_booting_touches_nothing(tmp_path: Path) -> None:
    async with await _kernel(tmp_path, warming=False).boot() as booted:
        await (await booted.container.get(CacheWarmerAggregate)).warm_up(Path("/cache"))
        await (await booted.container.get(ChainCacheClearer)).clear(Path("/cache"))

    assert not (tmp_path / "var").exists()
