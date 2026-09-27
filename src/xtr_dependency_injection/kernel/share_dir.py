"""Where a project keeps files its processes share: the ``kernel.share_dir`` parameter."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["share_dir"]


def share_dir(project_dir: Path) -> Path:
    """Return ``var/share`` in the project: where the project's processes share files.

    Cache files, lock files — whatever the processes of one application share
    on a machine goes here. Inside the project it belongs to whoever owns the
    project, and no other user of the machine can have made it first, as
    anyone can in the system's temporary directory; keep ``var/`` out of
    version control. Nothing is created: whatever writes first creates what it
    needs.
    """
    return project_dir / "var" / "share"
