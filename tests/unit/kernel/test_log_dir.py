from __future__ import annotations

from pathlib import Path

import pytest

from xtr_dependency_injection import Kernel
from xtr_dependency_injection.kernel.log_dir import log_dir

pytestmark = pytest.mark.anyio


def test_it_is_var_log_in_the_project() -> None:
    assert log_dir(Path("/srv/app")) == Path("/srv/app/var/log")


def test_two_projects_never_share_one() -> None:
    assert log_dir(Path("/srv/a")) != log_dir(Path("/srv/b"))


async def test_the_kernel_provides_it_as_a_parameter_without_creating_it() -> None:
    async with await Kernel(__name__, env="test", bundles={}, resources=()).boot() as booted:
        project_dir = Path(str(booted.container.get_parameter("kernel.project_dir")))
        logs = str(booted.container.get_parameter("kernel.log_dir"))

    assert logs == str(project_dir / "var" / "log")
    assert not (project_dir / "var" / "log").exists()
