"""What ``Kernel(exclude=..., default_excludes=...)`` leaves out of the scan."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from xtr_dependency_injection.exception import ResourceImportError
from xtr_dependency_injection.kernel import Kernel

if TYPE_CHECKING:
    from tests.support.modules import ScratchModules

_REFUSE = 'raise RuntimeError("the scan must never import this module")\n'


def _write_app(scratch_modules: ScratchModules, package: str) -> None:
    scratch_modules.write(
        {
            f"{package}.services": "",
            f"{package}.scripts.seed": _REFUSE,
            f"{package}.conftest": _REFUSE,
            f"{package}.tools.helper": _REFUSE,
        }
    )


def test_a_relative_pattern_is_taken_from_the_application_package(
    scratch_modules: ScratchModules,
) -> None:
    _write_app(scratch_modules, "rel_shop")

    compiled = Kernel("rel_shop", env="dev", bundles={}, exclude=(".scripts", ".tools")).build()

    assert compiled.report.scan.modules == ("rel_shop", "rel_shop.services")


def test_an_absolute_pattern_is_taken_as_written(scratch_modules: ScratchModules) -> None:
    _write_app(scratch_modules, "abs_shop")

    compiled = Kernel(
        "abs_shop", env="dev", bundles={}, exclude=("abs_shop.scripts", "*.tools")
    ).build()

    assert compiled.report.scan.modules == ("abs_shop", "abs_shop.services")


def test_a_relative_pattern_names_the_application_package_whatever_is_scanned(
    scratch_modules: ScratchModules,
) -> None:
    _write_app(scratch_modules, "res_shop")
    scratch_modules.write({"res_shop.inner.tools.helper": _REFUSE, "res_shop.inner.ok": ""})

    compiled = Kernel(
        "res_shop", env="dev", bundles={}, resources=("res_shop.inner",), exclude=(".inner.tools",)
    ).build()

    assert compiled.report.scan.modules == ("res_shop.inner", "res_shop.inner.ok")


def test_the_defaults_still_apply_beside_the_given_patterns(
    scratch_modules: ScratchModules,
) -> None:
    _write_app(scratch_modules, "def_shop")

    compiled = Kernel("def_shop", env="dev", bundles={}, exclude=(".scripts", ".tools")).build()

    assert "def_shop.conftest" not in compiled.report.scan.modules


def test_dropping_the_defaults_scans_what_they_left_out(scratch_modules: ScratchModules) -> None:
    _write_app(scratch_modules, "raw_shop")
    kernel = Kernel(
        "raw_shop", env="dev", bundles={}, exclude=(".scripts", ".tools"), default_excludes=False
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = kernel.build()

    assert caught.value.module == "raw_shop.conftest"


def test_another_environment_keeps_the_excludes(scratch_modules: ScratchModules) -> None:
    _write_app(scratch_modules, "env_shop")
    kernel = Kernel(
        "env_shop", env="dev", bundles={}, exclude=(".scripts", ".tools"), default_excludes=False
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = kernel.with_env("prod").build()

    assert caught.value.module == "env_shop.conftest"
