from __future__ import annotations

from typing import TYPE_CHECKING, final

import pytest
from typing_extensions import override

from xtr_dependency_injection.cache_warmer import CacheWarmer
from xtr_dependency_injection.exception import CacheFileWriteError

if TYPE_CHECKING:
    from pathlib import Path


@final
class FileWarmer(CacheWarmer):
    @override
    async def warm_up(self, cache_dir: Path, build_dir: Path | None = None) -> None:
        del build_dir
        self._write_cache_file(cache_dir / "routes.json", "{}")

    @override
    def is_optional(self) -> bool:
        return True


def test_it_writes_text_as_utf8(tmp_path: Path) -> None:
    FileWarmer()._write_cache_file(tmp_path / "routes.json", "ăî")

    assert (tmp_path / "routes.json").read_bytes() == "ăî".encode()


def test_it_replaces_a_file_already_there_and_leaves_nothing_beside_it(tmp_path: Path) -> None:
    _ = (tmp_path / "routes.json").write_text("old")

    FileWarmer()._write_cache_file(tmp_path / "routes.json", b"new")

    assert [path.name for path in tmp_path.iterdir()] == ["routes.json"]
    assert (tmp_path / "routes.json").read_bytes() == b"new"


def test_a_file_that_cannot_be_written_raises_naming_it(tmp_path: Path) -> None:
    file = tmp_path / "missing" / "routes.json"

    with pytest.raises(CacheFileWriteError) as raised:
        FileWarmer()._write_cache_file(file, "x")

    assert raised.value.path == file
    assert isinstance(raised.value.__cause__, OSError)
