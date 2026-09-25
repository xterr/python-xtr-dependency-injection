"""Booting a kernel in tests, and the zero-config check every bundle's suite runs."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from xtr_dependency_injection.kernel.kernel import Kernel

if TYPE_CHECKING:
    from collections.abc import Hashable, Mapping

    from xtr_dependency_injection.bundle.bundle import AnyBundle
    from xtr_dependency_injection.kernel.booted_kernel import BootedKernel

__all__ = ["assert_zero_config", "boot_for_test"]

_NO_OVERRIDES: Final[Mapping[type | tuple[type, Hashable], object]] = MappingProxyType({})


async def boot_for_test(
    kernel: Kernel,
    /,
    *,
    env: str = "test",
    overrides: Mapping[type | tuple[type, Hashable], object] = _NO_OVERRIDES,
) -> BootedKernel:
    """Build ``kernel`` for ``env``, apply ``overrides``, and boot it.

    Overrides are in place before any boot hook runs. A key is a type, or a
    ``(type, qualifier)`` pair for a qualified service::

        async with await boot_for_test(kernel, overrides={Mailer: FakeMailer()}) as booted:
            ...
    """
    compiled = kernel.with_env(env).build()
    for key, replacement in overrides.items():
        provided, qualifier = key if isinstance(key, tuple) else (key, None)
        compiled.container.override.set(provided, replacement, qualifier=qualifier)
    return await compiled.boot()


async def assert_zero_config(bundle_cls: type[AnyBundle], /) -> None:
    """Build, boot and shut down a kernel of ``bundle_cls`` alone, with its default config.

    Its requirements come from what is installed; nothing is scanned. Call it
    from every bundle's test suite: a bundle that arrives transitively must
    work without the application configuring it.

    Raises:
        Exception: Whatever building, booting or shutting down raised.
    """
    metadata = bundle_cls.metadata()
    env = metadata.envs[0] if metadata.envs else "test"
    kernel = Kernel(bundle_cls.__module__, env=env, bundles=[bundle_cls()], resources=())
    booted = await kernel.boot()
    await booted.shutdown()
