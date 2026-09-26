from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest

from xtr_dependency_injection import Kernel
from xtr_dependency_injection.kernel.share_dir import share_dir

pytestmark = pytest.mark.anyio


def test_it_is_the_projects_digest_under_the_temporary_directory() -> None:
    project = Path("/srv/app")
    digest = hashlib.sha256(b"/srv/app").hexdigest()[:16]

    assert share_dir(project) == Path(tempfile.gettempdir()) / "xtr" / digest


def test_two_projects_never_share_one() -> None:
    assert share_dir(Path("/srv/a")) != share_dir(Path("/srv/b"))


async def test_the_kernel_provides_it_as_a_parameter_without_creating_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    async with await Kernel(__name__, env="test", bundles={}, resources=()).boot() as booted:
        project_dir = Path(str(booted.container.get_parameter("kernel.project_dir")))
        shared = str(booted.container.get_parameter("kernel.share_dir"))

    assert shared == str(share_dir(project_dir))
    assert shared.startswith(str(tmp_path))
    assert not (tmp_path / "xtr").exists()
