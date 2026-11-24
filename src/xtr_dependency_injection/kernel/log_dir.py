"""Where a project keeps its log files: the ``kernel.log_dir`` parameter."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["log_dir"]


def log_dir(project_dir: Path) -> Path:
    """Return ``var/log`` in the project: where the project's processes write logs.

    Every environment's logs go here — logs are shared across environments,
    so unlike the cache this directory is not scoped to one. Inside the
    project it belongs to whoever owns the project, and no other user of the
    machine can have made it first, as anyone can in the system's temporary
    directory; keep ``var/`` out of version control. Nothing is created:
    whatever writes first creates what it needs.
    """
    return project_dir / "var" / "log"
