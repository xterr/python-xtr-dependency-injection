from __future__ import annotations

from pathlib import Path
from typing import final

import pytest
from typing_extensions import override

from xtr_dependency_injection.cache_clearer import CacheClearerInterface, ChainCacheClearer


@final
class RecordingClearer(CacheClearerInterface):
    def __init__(self, name: str, log: list[tuple[str, Path]]) -> None:
        self._name = name
        self._log = log

    @override
    async def clear(self, cache_dir: Path) -> None:
        self._log.append((self._name, cache_dir))


@pytest.mark.anyio
async def test_it_runs_every_clearer_in_order_on_the_cache_directory() -> None:
    log: list[tuple[str, Path]] = []
    chain = ChainCacheClearer([RecordingClearer("first", log), RecordingClearer("second", log)])

    await chain.clear(Path("/cache"))

    assert log == [("first", Path("/cache")), ("second", Path("/cache"))]
