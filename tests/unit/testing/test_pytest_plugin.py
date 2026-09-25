from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

CONFTEST = """
import pytest

from xtr_dependency_injection import Kernel

pytest_plugins = ["xtr_dependency_injection.testing.pytest_plugin"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
"""

OVERRIDDEN = """
import pytest

from xtr_dependency_injection import Kernel, KernelInterface


@pytest.fixture
def xtr_kernel() -> Kernel:
    return Kernel("json", resources=())


@pytest.mark.anyio
async def test_booted(booted_kernel, container) -> None:
    info = await container.get(KernelInterface)
    assert booted_kernel.kernel is info
    assert info.environment == "test"
"""

NOT_OVERRIDDEN = """
import pytest


@pytest.mark.anyio
async def test_booted(booted_kernel) -> None:
    pass
"""


def test_the_fixtures_boot_the_overridden_kernel(pytester: pytest.Pytester) -> None:
    _ = pytester.makeconftest(CONFTEST)
    _ = pytester.makepyfile(OVERRIDDEN)

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1)


def test_the_kernel_fixture_must_be_overridden(pytester: pytest.Pytester) -> None:
    _ = pytester.makeconftest(CONFTEST)
    _ = pytester.makepyfile(NOT_OVERRIDDEN)

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*override the xtr_kernel fixture*"])
