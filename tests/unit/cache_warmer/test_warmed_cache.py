from __future__ import annotations

from typing import TYPE_CHECKING

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


def test_holding_it_creates_the_directory(tmp_path: Path) -> None:
    cache_dir = tmp_path / "var" / "cache" / "prod"

    with WarmedCache(cache_dir, "build 1").lock():
        assert cache_dir.is_dir()
