"""Where a project keeps files its processes share: the ``kernel.share_dir`` parameter."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Final

__all__ = ["share_dir"]

_DIGEST_LENGTH: Final = 16


def share_dir(project_dir: Path) -> Path:
    """Return the project's own directory under the system's temporary one.

    Cache files, lock files — whatever the processes of one application share
    on a machine goes here. It is the project directory's digest rather than
    a directory inside the project, so nothing is ever written into the
    source tree and two projects on one machine never share files. Nothing is
    created: whatever writes first creates what it needs.
    """
    digest = hashlib.sha256(str(project_dir).encode()).hexdigest()[:_DIGEST_LENGTH]
    return Path(tempfile.gettempdir()) / "xtr" / digest
