"""The core ``kernel`` bundle: always active, always first, never discovered.

It provides what every application may ask for: :class:`KernelInterface`,
the :class:`ServicesResetter`, the :class:`CacheWarmerAggregate` and
:class:`ChainCacheClearer` holding every cache warmer and clearer, and —
through the kernel wiring in :func:`_register_kernel_parameters` — the
``kernel.*`` parameters. Every
active bundle's resolved config is also registered under its config type by
the kernel, right after this bundle's ``load_extension`` returns.

Booting it warms the cache when the cache directory is cold — the first start,
and the first after ``cache:clear`` or a change to a warmer — before any other
bundle boots, so they find what the warmers wrote.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, final

from typing_extensions import override
from wireup import AsyncContainer
from xtr_service_contracts import ContainerInterface, ResetInterface

from xtr_dependency_injection.bundle import KERNEL_BUNDLE, Bundle, BundleMetadata, NoConfig
from xtr_dependency_injection.bundle.as_bundle import declare_bundle
from xtr_dependency_injection.cache_clearer import CacheClearerInterface, ChainCacheClearer
from xtr_dependency_injection.cache_warmer import (
    CacheWarmerAggregate,
    CacheWarmerInterface,
    WarmedCache,
)
from xtr_dependency_injection.compiler.add_cache_clearer_pass import (
    CACHE_CLEARER_TAG,
    AddCacheClearerPass,
)
from xtr_dependency_injection.compiler.add_cache_warmer_pass import (
    CACHE_WARMER_TAG,
    AddCacheWarmerPass,
)
from xtr_dependency_injection.compiler.check_alias_validity_pass import CheckAliasValidityPass
from xtr_dependency_injection.compiler.pass_stage import BUNDLE_PASS_PRIORITY, PassStage
from xtr_dependency_injection.compiler.register_env_var_processors_pass import (
    ENV_VAR_LOADER_TAG,
    ENV_VAR_PROCESSOR_TAG,
)
from xtr_dependency_injection.compiler.resettable_service_pass import (
    RESET_TAG,
    ResettableServicePass,
)
from xtr_dependency_injection.parameter_bag.container_bag import ContainerBag
from xtr_dependency_injection.parameter_bag.container_bag_interface import ContainerBagInterface
from xtr_dependency_injection.runtime.env_var_loader_interface import EnvVarLoaderInterface
from xtr_dependency_injection.runtime.env_var_processor_interface import EnvVarProcessorInterface
from xtr_dependency_injection.runtime.scope_factory import ScopeFactory
from xtr_dependency_injection.runtime.scope_factory_interface import ScopeFactoryInterface
from xtr_dependency_injection.runtime.service_locator import ServiceLocator
from xtr_dependency_injection.runtime.services_resetter import ServicesResetter
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

# _KernelInfo is the one KernelInterface implementation, and this bundle is
# the only module besides its own allowed to build it.
from .kernel_interface import KernelInterface, _KernelInfo  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.service_configurator import ServiceConfigurator
    from xtr_dependency_injection.diagnostics import KernelReport

__all__ = ["KernelBundle"]


def container_bag(container: ContainerInterface, engine: AsyncContainer) -> ContainerBagInterface:
    """Expose the compiled container's parameters as an injectable, read-only bag.

    The parameters are read off the engine itself: the container interface
    may be replaced — by a test's override — and need not know them.
    """
    return ContainerBag(container, WireupContainer(engine).get_parameters())


def container_interface(container: AsyncContainer) -> ContainerInterface:
    """Wrap the engine container behind :class:`ContainerInterface`.

    Registered by :class:`KernelBundle`; wireup evaluates the annotation and
    keys the service under :class:`ContainerInterface`.
    """
    return WireupContainer(container)


def scope_factory(container: ContainerInterface) -> ScopeFactoryInterface:
    """Provide the :class:`ScopeFactoryInterface` that opens units of work on the container.

    A service injects this rather than the whole container when all it needs
    is to open a unit of work.
    """
    return ScopeFactory(container)


async def cache_warmer_aggregate(
    warmers: ServiceLocator[CacheWarmerInterface], warmer_names: Sequence[str]
) -> CacheWarmerAggregate:
    """Provide the :class:`CacheWarmerAggregate` running every ``kernel.cache_warmer`` service.

    Args:
        warmers: The tagged warmers, built only when the aggregate is.
        warmer_names: Their qualifiers, run first first — written by
            :class:`~xtr_dependency_injection.compiler.add_cache_warmer_pass.AddCacheWarmerPass`.
    """
    return CacheWarmerAggregate([await warmers.get(name) for name in warmer_names])


async def chain_cache_clearer(
    clearers: ServiceLocator[CacheClearerInterface], clearer_names: Sequence[str]
) -> ChainCacheClearer:
    """Provide the :class:`ChainCacheClearer` running every ``kernel.cache_clearer`` service.

    Args:
        clearers: The tagged clearers, built only when the chain is.
        clearer_names: Their qualifiers, run first first — written by
            :class:`~xtr_dependency_injection.compiler.add_cache_clearer_pass.AddCacheClearerPass`.
    """
    return ChainCacheClearer([await clearers.get(name) for name in clearer_names])


def warmed_cache(kernel: KernelInterface, parameters: ContainerBagInterface) -> WarmedCache:
    """Provide the :class:`WarmedCache` telling whether the warmers filled the cache for this build.

    The build is told apart by the environment, the debug flag, and every
    ``kernel.cache_warmer`` service's provider with the time its module was
    last written: adding, removing or upgrading a warmer makes the cache cold.
    ``kernel.cache_dir`` is read when it is built, so a container built
    without a kernel can still hold this definition.
    """
    return WarmedCache(Path(str(parameters.get("kernel.cache_dir"))), _fingerprint(kernel))


def _warmers(report: KernelReport) -> list[str]:
    """Return the provider of every ``kernel.cache_warmer`` service, sorted."""
    return sorted(
        definition.provider_qualname
        for definition in report.definitions
        if CACHE_WARMER_TAG in definition.tags
    )


def _fingerprint(kernel: KernelInterface) -> str:
    lines = [f"environment {kernel.environment}", f"debug {kernel.debug}"]
    lines.extend(f"{provider} {_written(provider)}" for provider in _warmers(kernel.report))
    return "\n".join(lines) + "\n"


def _written(provider: str) -> str:
    """Return when the module defining ``provider`` (``module:qualname``) was last written."""
    module = sys.modules.get(provider.partition(":")[0])
    file = getattr(module, "__file__", None)
    if not isinstance(file, str):
        return "unknown"
    try:
        return str(Path(file).stat().st_mtime_ns)
    except OSError:
        return "unknown"


def _create(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)


@final
@declare_bundle(BundleMetadata(KERNEL_BUNDLE, NoConfig))
class KernelBundle(Bundle):
    """Provides the kernel's own services to every container."""

    def __init__(self) -> None:
        """Create the kernel's info and resetter; the kernel fills in the info as it builds."""
        self.info: _KernelInfo = _KernelInfo()
        self.resetter: ServicesResetter = ServicesResetter()

    @override
    def build(self, builder: ContainerBuilder) -> None:
        """Register the kernel's compiler passes and autoconfiguration rules.

        :class:`ResettableServicePass` checks every ``kernel.reset`` method
        (``BEFORE_OPTIMIZATION`` -32); :class:`CheckAliasValidityPass` checks
        every alias target implements its alias (``BEFORE_REMOVING``). Every
        non-kernel service implementing ``ResetInterface`` (nominal subclass,
        not structural) gets ``kernel.reset`` with ``method="reset"``; a
        service opts in explicitly with ``add_tag("kernel.reset", method=…)``.
        Every one implementing ``EnvVarProcessorInterface`` or
        ``EnvVarLoaderInterface`` is tagged for ``RegisterEnvVarProcessorsPass``.
        Every one implementing ``CacheWarmerInterface`` or
        ``CacheClearerInterface`` gets ``kernel.cache_warmer`` or
        ``kernel.cache_clearer``, which :class:`AddCacheWarmerPass` and
        :class:`AddCacheClearerPass` collect after every bundle's ``process``
        hook has run.
        """
        builder.add_compiler_pass(
            ResettableServicePass(), stage=PassStage.BEFORE_OPTIMIZATION, priority=-32
        )
        builder.add_compiler_pass(CheckAliasValidityPass(), stage=PassStage.BEFORE_REMOVING)
        for collecting_pass in (AddCacheWarmerPass(), AddCacheClearerPass()):
            builder.add_compiler_pass(
                collecting_pass,
                stage=PassStage.BEFORE_OPTIMIZATION,
                priority=BUNDLE_PASS_PRIORITY,
            )
        _ = builder.register_for_autoconfiguration(ResetInterface).add_tag(
            RESET_TAG, method="reset"
        )
        _ = builder.register_for_autoconfiguration(EnvVarProcessorInterface).add_tag(
            ENV_VAR_PROCESSOR_TAG
        )
        _ = builder.register_for_autoconfiguration(EnvVarLoaderInterface).add_tag(
            ENV_VAR_LOADER_TAG
        )
        _ = builder.register_for_autoconfiguration(CacheWarmerInterface).add_tag(CACHE_WARMER_TAG)
        _ = builder.register_for_autoconfiguration(CacheClearerInterface).add_tag(CACHE_CLEARER_TAG)

    @override
    def load_extension(
        self, config: NoConfig, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config, builder
        _ = services.instance(self.info)
        services.alias(KernelInterface, _KernelInfo)
        _ = services.instance(self.resetter)
        _ = services.set(container_interface)
        _ = services.set(scope_factory)
        _ = services.set(container_bag)
        _ = services.set(cache_warmer_aggregate).set_argument("warmer_names", [])
        _ = services.set(chain_cache_clearer).set_argument("clearer_names", [])
        _ = services.set(warmed_cache)

    @override
    async def boot(self) -> None:
        """Warm the cache when it is cold, before any other bundle boots.

        Only the warmers that are not optional run, and only while
        :class:`WarmedCache` says the cache directory was not filled for this
        build; every later start reads one small file and goes on. One process
        at a time warms: another starting meanwhile waits, then finds the
        cache warm. An application without warmers touches nothing.
        """
        container = self.container
        if container is None:  # pragma: no cover — the kernel sets this before boot.
            message = "KernelBundle.boot ran without a container"
            raise RuntimeError(message)
        if not _warmers(self.info.report):
            return
        cache = await container.get(WarmedCache)
        if cache.is_fresh():
            return
        cache_dir = Path(str(container.get_parameter("kernel.cache_dir")))
        build_dir = Path(str(container.get_parameter("kernel.build_dir")))
        with cache.lock():
            if cache.is_fresh():
                return
            _create(build_dir)
            await (await container.get(CacheWarmerAggregate)).warm_up(cache_dir, build_dir)
            cache.mark_fresh()
