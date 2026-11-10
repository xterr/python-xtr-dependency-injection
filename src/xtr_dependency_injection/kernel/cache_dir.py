"""Where an application keeps its cache: the ``kernel.cache_dir`` parameter."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["cache_dir"]


def cache_dir(project_dir: Path, environment: str) -> Path:
    """Return ``var/cache/<environment>`` in the project: the environment's cache.

    One directory per environment, so warming the cache of one never serves
    another, and ``cache:clear`` removes only its own. Everything in it can be
    rebuilt; keep ``var/`` out of version control. Nothing is created here:
    the kernel creates it when it warms a cold cache at boot, as do the cache
    commands.
    """
    return project_dir / "var" / "cache" / environment
