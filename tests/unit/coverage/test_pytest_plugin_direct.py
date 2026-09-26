"""Directly execute the opt-in pytest plugin fixtures for coverage.

The plugin already has an end-to-end test through ``pytester`` (subprocess), which does not
count toward coverage. Here we drive each fixture as a plain function/generator by unwrapping
the ``FixtureFunctionDefinition`` down to the underlying body.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import cast

import pytest
from xtr_service_contracts import ContainerInterface

from xtr_dependency_injection import Kernel
from xtr_dependency_injection.kernel.booted_kernel import BootedKernel
from xtr_dependency_injection.testing import pytest_plugin

_KernelFn = Callable[[], Kernel]
_BootedFn = Callable[[Kernel], AsyncIterator[BootedKernel]]
_ContainerFn = Callable[[BootedKernel], ContainerInterface]


def test_xtr_kernel_fixture_fails_when_not_overridden() -> None:
    body = cast("_KernelFn", getattr(pytest_plugin.xtr_kernel, "__wrapped__"))  # noqa: B009
    with pytest.raises(pytest.fail.Exception, match="override the xtr_kernel fixture"):
        _ = body()


@pytest.mark.anyio
async def test_booted_kernel_and_container_fixtures_yield_a_working_container() -> None:
    kernel = Kernel("xtr_dependency_injection", bundles={}, resources=())
    booted_body = cast("_BootedFn", getattr(pytest_plugin.booted_kernel, "__wrapped__"))  # noqa: B009
    container_body = cast("_ContainerFn", getattr(pytest_plugin.container, "__wrapped__"))  # noqa: B009

    gen = booted_body(kernel)
    booted = await gen.__anext__()
    try:
        container = container_body(booted)
        assert container is booted.container
        assert container.has_parameter("kernel.environment")
    finally:
        with pytest.raises(StopAsyncIteration):
            _ = await gen.__anext__()
