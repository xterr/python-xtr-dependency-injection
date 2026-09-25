"""Opt-in pytest fixtures for applications built on a kernel.

Enable it in ``conftest.py`` and override ``xtr_kernel``::

    pytest_plugins = ["xtr_dependency_injection.testing.pytest_plugin"]


    @pytest.fixture
    def xtr_kernel() -> Kernel:
        return kernel

Tests then take ``booted_kernel`` or ``container``. Async tests run through
anyio.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from . import boot_for_test

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from wireup import AsyncContainer

    from xtr_dependency_injection.kernel.booted_kernel import BootedKernel
    from xtr_dependency_injection.kernel.kernel import Kernel

__all__ = ["booted_kernel", "container", "xtr_kernel"]


@pytest.fixture
def xtr_kernel() -> Kernel:
    """Return the application's kernel; override this fixture in the project."""
    pytest.fail("override the xtr_kernel fixture to return your application's Kernel")


@pytest.fixture
async def booted_kernel(xtr_kernel: Kernel) -> AsyncIterator[BootedKernel]:
    """Boot the kernel for the ``test`` environment, and shut it down after the test."""
    booted = await boot_for_test(xtr_kernel)
    try:
        yield booted
    finally:
        await booted.shutdown()


@pytest.fixture
def container(booted_kernel: BootedKernel) -> AsyncContainer:
    """Return the booted kernel's container."""
    return booted_kernel.container
