"""Whether the cache directory holds what this build's warmers write."""

from __future__ import annotations

import secrets
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final, final

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

__all__ = ["WarmedCache"]

_STAMP: Final = ".warmed"
_LOCK: Final = ".warmed.lock"


@final
class WarmedCache:
    """Records, in the cache directory, which build its warmers last filled it for.

    The kernel warms the cache when it boots only while the directory is not
    fresh — it holds no stamp, or one written for another build — so every
    later start skips the warm-up. ``cache:clear`` removes the directory, and
    with it the stamp, so the next start warms again.

    A build is told apart by its ``fingerprint``: whatever, when it changes,
    makes what the warmers wrote stale.
    """

    __slots__ = ("_cache_dir", "_fingerprint")

    def __init__(self, cache_dir: Path, fingerprint: str) -> None:
        """Keep the stamp in ``cache_dir``, for the build ``fingerprint`` names."""
        self._cache_dir = cache_dir
        self._fingerprint = fingerprint

    def is_fresh(self) -> bool:
        """Tell whether the warmers already filled the cache directory for this build."""
        try:
            return (self._cache_dir / _STAMP).read_text(encoding="utf-8") == self._fingerprint
        except OSError:
            return False

    def mark_fresh(self) -> None:
        """Record that the warmers filled the cache directory for this build.

        The stamp is replaced in one step, so a process reading it meanwhile
        sees the old one or the new one.
        """
        stamp = self._cache_dir / _STAMP
        temporary = stamp.with_name(f"{_STAMP}.{secrets.token_hex(8)}")
        _ = temporary.write_text(self._fingerprint, encoding="utf-8")
        _ = temporary.replace(stamp)

    @contextmanager
    def lock(self) -> Generator[None, None, None]:
        """Hold the cache directory, creating it, so one process at a time warms it.

        The lock is a file lock: it holds across processes, and is let go
        whatever happens, even when the process dies. Where file locks are not
        available it holds nothing.
        """
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        with (self._cache_dir / _LOCK).open("a") as handle:
            if sys.platform != "win32":
                import fcntl  # noqa: PLC0415 — only where the platform has it.

                fcntl.flock(handle, fcntl.LOCK_EX)
            yield
