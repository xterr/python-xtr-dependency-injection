from __future__ import annotations

from pathlib import Path
from typing import final

import pytest
from typing_extensions import override

from xtr_dependency_injection.cache_warmer import CacheWarmerAggregate, CacheWarmerInterface

pytestmark = pytest.mark.anyio


@final
class RecordingWarmer(CacheWarmerInterface):
    def __init__(
        self, name: str, log: list[tuple[str, Path, Path | None]], *, optional: bool
    ) -> None:
        self._name = name
        self._log = log
        self._optional = optional

    @override
    async def warm_up(self, cache_dir: Path, build_dir: Path | None = None) -> None:
        self._log.append((self._name, cache_dir, build_dir))

    @override
    def is_optional(self) -> bool:
        return self._optional


def _aggregate(log: list[tuple[str, Path, Path | None]]) -> CacheWarmerAggregate:
    return CacheWarmerAggregate(
        [
            RecordingWarmer("required", log, optional=False),
            RecordingWarmer("optional", log, optional=True),
        ]
    )


def _names(log: list[tuple[str, Path, Path | None]]) -> list[str]:
    return [name for name, _, _ in log]


async def test_only_the_warmers_that_are_not_optional_run_by_default() -> None:
    log: list[tuple[str, Path, Path | None]] = []

    await _aggregate(log).warm_up(Path("/cache"), Path("/build"))

    assert log == [("required", Path("/cache"), Path("/build"))]


async def test_enabling_the_optional_warmers_runs_every_one_in_order() -> None:
    log: list[tuple[str, Path, Path | None]] = []
    aggregate = _aggregate(log)
    aggregate.enable_optional_warmers()

    await aggregate.warm_up(Path("/cache"))

    assert _names(log) == ["required", "optional"]


async def test_enabling_only_the_optional_warmers_skips_the_others() -> None:
    log: list[tuple[str, Path, Path | None]] = []
    aggregate = _aggregate(log)
    aggregate.enable_only_optional_warmers()

    await aggregate.warm_up(Path("/cache"))

    assert _names(log) == ["optional"]


def test_the_aggregate_is_never_optional() -> None:
    assert not CacheWarmerAggregate().is_optional()
