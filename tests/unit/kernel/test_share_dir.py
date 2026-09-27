from __future__ import annotations

from pathlib import Path

import pytest

from xtr_dependency_injection import Kernel
from xtr_dependency_injection.kernel.share_dir import share_dir

pytestmark = pytest.mark.anyio


def test_it_is_var_share_in_the_project() -> None:
    assert share_dir(Path("/srv/app")) == Path("/srv/app/var/share")


def test_two_projects_never_share_one() -> None:
    assert share_dir(Path("/srv/a")) != share_dir(Path("/srv/b"))


async def test_the_kernel_provides_it_as_a_parameter_without_creating_it() -> None:
    async with await Kernel(__name__, env="test", bundles={}, resources=()).boot() as booted:
        project_dir = Path(str(booted.container.get_parameter("kernel.project_dir")))
        shared = str(booted.container.get_parameter("kernel.share_dir"))

    assert shared == str(project_dir / "var" / "share")
    assert not (project_dir / "var" / "share").exists()
