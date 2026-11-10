from __future__ import annotations

from pathlib import Path

import pytest

from xtr_dependency_injection import Kernel
from xtr_dependency_injection.kernel.cache_dir import cache_dir

pytestmark = pytest.mark.anyio


def test_it_is_var_cache_and_the_environment_in_the_project() -> None:
    assert cache_dir(Path("/srv/app"), "prod") == Path("/srv/app/var/cache/prod")


def test_two_environments_never_share_one() -> None:
    assert cache_dir(Path("/srv/app"), "dev") != cache_dir(Path("/srv/app"), "test")


async def test_the_kernel_provides_it_and_the_build_dir_without_creating_them() -> None:
    async with await Kernel(__name__, env="test", bundles={}, resources=()).boot() as booted:
        project_dir = Path(str(booted.container.get_parameter("kernel.project_dir")))
        cached = str(booted.container.get_parameter("kernel.cache_dir"))
        built = str(booted.container.get_parameter("kernel.build_dir"))

    assert cached == built == str(project_dir / "var" / "cache" / "test")
    assert not (project_dir / "var" / "cache").exists()
