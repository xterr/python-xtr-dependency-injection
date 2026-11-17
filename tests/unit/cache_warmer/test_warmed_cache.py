from __future__ import annotations

import asyncio
import fcntl
from typing import TYPE_CHECKING

import pytest

from xtr_dependency_injection.cache_warmer import WarmedCache

if TYPE_CHECKING:
    from pathlib import Path


def test_a_directory_without_a_stamp_is_not_fresh(tmp_path: Path) -> None:
    assert not WarmedCache(tmp_path / "missing", "build 1").is_fresh()


def test_marking_it_fresh_makes_it_fresh_for_that_build_only(tmp_path: Path) -> None:
    WarmedCache(tmp_path, "build 1").mark_fresh()

    assert WarmedCache(tmp_path, "build 1").is_fresh()
    assert not WarmedCache(tmp_path, "build 2").is_fresh()


def test_marking_it_fresh_leaves_only_the_stamp(tmp_path: Path) -> None:
    WarmedCache(tmp_path, "build 1").mark_fresh()

    assert [path.name for path in tmp_path.iterdir()] == [".warmed"]


@pytest.mark.anyio
async def test_holding_it_creates_the_directory(tmp_path: Path) -> None:
    cache_dir = tmp_path / "var" / "cache" / "prod"

    async with WarmedCache(cache_dir, "build 1").lock():
        assert cache_dir.is_dir()


@pytest.mark.anyio
async def test_waiting_for_the_lock_does_not_block_the_loop(tmp_path: Path) -> None:
    # Another process holds the lock: the wait must let the loop run, and be cancellable.
    cache = WarmedCache(tmp_path, "build 1")
    async with cache.lock():
        pass
    with (tmp_path / ".warmed.lock").open("a") as other:
        fcntl.flock(other, fcntl.LOCK_EX)
        ticks = 0
        waiting = asyncio.create_task(_hold(cache))
        for _ in range(5):
            await asyncio.sleep(0.02)
            ticks += 1
        assert not waiting.done()
        fcntl.flock(other, fcntl.LOCK_UN)
        await asyncio.wait_for(waiting, 2)

    assert ticks == 5


@pytest.mark.anyio
async def test_a_wait_for_the_lock_can_be_cancelled(tmp_path: Path) -> None:
    cache = WarmedCache(tmp_path, "build 1")
    async with cache.lock():
        pass
    with (tmp_path / ".warmed.lock").open("a") as other:
        fcntl.flock(other, fcntl.LOCK_EX)
        waiting = asyncio.create_task(_hold(cache))
        await asyncio.sleep(0.05)
        _ = waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting


async def _hold(cache: WarmedCache) -> None:
    async with cache.lock():
        pass
