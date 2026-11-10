"""A base for cache warmers that write files."""

from __future__ import annotations

import secrets
from abc import ABC
from typing import TYPE_CHECKING

from xtr_dependency_injection.exception import CacheFileWriteError

from .cache_warmer_interface import CacheWarmerInterface

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["CacheWarmer"]


class CacheWarmer(CacheWarmerInterface, ABC):
    """A cache warmer that knows how to write a file into the cache.

    A subclass implements :meth:`warm_up` and :meth:`is_optional`, and writes
    each file it produces through :meth:`_write_cache_file`.
    """

    def _write_cache_file(self, file: Path, content: str | bytes) -> None:
        """Write ``content`` to ``file`` whole, or leave ``file`` as it was.

        The content goes to a new file beside it first, which then replaces
        ``file`` in one step: a process reading the cache meanwhile sees the
        old file or the new one, never half of either. The new file is created
        with the permissions the process creates any file with. Text is
        written as UTF-8.

        Raises:
            CacheFileWriteError: When the file cannot be written; the
                filesystem's error is its ``__cause__``.
        """
        data = content.encode() if isinstance(content, str) else content
        temporary = file.with_name(f".{file.name}.{secrets.token_hex(8)}")
        try:
            with temporary.open("xb") as stream:
                _ = stream.write(data)
            _ = temporary.replace(file)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise CacheFileWriteError(file) from error
