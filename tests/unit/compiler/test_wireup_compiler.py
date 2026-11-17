"""Building singletons in a debug kernel: what belongs to one unit of work is refused."""

from __future__ import annotations

import pytest

from tests.fixtures.app_singleton_reads_unit import KeepsUnit
from xtr_dependency_injection import Kernel, current_unit_of_work, unit_of_work
from xtr_dependency_injection.exception import (
    ServiceResolutionError,
    UnitReadDuringSingletonBuildError,
)

pytestmark = pytest.mark.anyio

_APP = "tests.fixtures.app_singleton_reads_unit"


async def test_reading_the_unit_while_a_singleton_is_built_raises_in_debug() -> None:
    async with (
        await Kernel(_APP, env="test", debug=True, bundles={}).boot() as booted,
        unit_of_work(booted.container) as unit,
    ):
        with pytest.raises(ServiceResolutionError) as raised:
            _ = await unit.get(KeepsUnit)

    assert isinstance(raised.value.__cause__, UnitReadDuringSingletonBuildError)


async def test_reading_the_unit_while_a_singleton_is_built_works_outside_debug() -> None:
    async with (
        await Kernel(_APP, env="test", debug=False, bundles={}).boot() as booted,
        unit_of_work(booted.container) as unit,
    ):
        kept = await unit.get(KeepsUnit)

    assert kept.unit is not None


async def test_the_unit_is_readable_again_once_a_singleton_build_failed() -> None:
    async with (
        await Kernel(_APP, env="test", debug=True, bundles={}).boot() as booted,
        unit_of_work(booted.container) as unit,
    ):
        with pytest.raises(ServiceResolutionError):
            _ = await unit.get(KeepsUnit)

        assert current_unit_of_work() is not None
