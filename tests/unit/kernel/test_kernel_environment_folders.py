"""Environment folders: ``config/packages/<env>/`` and ``config/routes/<env>/``."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from tests.support.bundles import EchoBundle, EchoConfig
from xtr_dependency_injection.exception import UnknownEnvironmentFolderError
from xtr_dependency_injection.kernel import Kernel

if TYPE_CHECKING:
    from tests.support.modules import ScratchModules
    from xtr_dependency_injection.kernel import CompiledKernel

_HEADER = """\
from dataclasses import replace

from tests.support.bundles import EchoConfig
from xtr_dependency_injection.config.configure import configure
from xtr_dependency_injection.decorator.when import when
"""

_COMMON = (
    _HEADER
    + """
@configure
def echo() -> EchoConfig:
    return EchoConfig(greeting="common")


@configure(priority=100)
def add_common(config: EchoConfig) -> EchoConfig:
    return replace(config, channels=(*config.channels, "common"))


@configure
@when("staging")
def add_staging(config: EchoConfig) -> EchoConfig:
    return replace(config, channels=(*config.channels, "staging"))
"""
)

_DEV = (
    _HEADER
    + """
@configure
def echo_dev() -> EchoConfig:
    return EchoConfig(greeting="dev")


@configure
def add_dev(config: EchoConfig) -> EchoConfig:
    return replace(config, channels=(*config.channels, "dev"))
"""
)

_DEV_INIT = (
    _HEADER
    + """
@configure(priority=-100)
def add_dev_init(config: EchoConfig) -> EchoConfig:
    return replace(config, channels=(*config.channels, "dev-init"))
"""
)

_NEEDS_A_DEV_DEPENDENCY = "import a_dev_dependency_that_is_not_installed  # noqa: F401\n"


def _write_app(scratch_modules: ScratchModules, package: str) -> None:
    scratch_modules.write(
        {
            f"{package}.config.packages.echo": _COMMON,
            f"{package}.config.packages.dev.__init__": _DEV_INIT,
            f"{package}.config.packages.dev.echo": _DEV,
            f"{package}.config.routes.main": "def main() -> None: ...\n",
            f"{package}.config.routes.dev.debug": "def debug() -> None: ...\n",
        }
    )


def _build(package: str, env: str, allowed_envs: tuple[str, ...] | None = None) -> CompiledKernel:
    return Kernel(
        package, env=env, bundles={EchoBundle: {"all": True}}, allowed_envs=allowed_envs
    ).build()


def _echo(compiled: CompiledKernel) -> object:
    return next(report.value for report in compiled.report.configs if report.bundle == "echo")


def test_another_environment_never_imports_the_folder(scratch_modules: ScratchModules) -> None:
    _write_app(scratch_modules, "prod_shop")
    scratch_modules.write({"prod_shop.config.packages.dev.tools": _NEEDS_A_DEV_DEPENDENCY})

    compiled = _build("prod_shop", "prod")

    assert _echo(compiled) == EchoConfig(greeting="common", channels=("common",))
    assert not [name for name in sys.modules if name.startswith("prod_shop.config.packages.dev")]
    assert not [name for name in compiled.report.scan.modules if ".dev" in name]


def test_another_environment_reports_the_folder_left_out(scratch_modules: ScratchModules) -> None:
    _write_app(scratch_modules, "skip_shop")

    compiled = _build("skip_shop", "prod")

    assert ("skip_shop.config.packages.dev", "environment folder for 'dev', not 'prod'") in (
        compiled.report.scan.skipped
    )


def test_the_folder_of_the_environment_overrides_the_common_config(
    scratch_modules: ScratchModules,
) -> None:
    _write_app(scratch_modules, "dev_shop")

    compiled = _build("dev_shop", "dev")

    # The folder's base replaces the common one; its transforms, its __init__'s
    # included, run after every common transform, whatever their priorities.
    assert _echo(compiled) == EchoConfig(greeting="dev", channels=("common", "dev", "dev-init"))


def test_the_folders_are_scanned_after_every_common_module(
    scratch_modules: ScratchModules,
) -> None:
    _write_app(scratch_modules, "order_shop")

    compiled = _build("order_shop", "dev")

    assert compiled.report.scan.modules[-5:] == (
        "order_shop.config.routes.main",
        "order_shop.config.packages.dev",
        "order_shop.config.packages.dev.echo",
        "order_shop.config.routes.dev",
        "order_shop.config.routes.dev.debug",
    )


def test_when_in_a_common_module_applies_to_any_environment(
    scratch_modules: ScratchModules,
) -> None:
    _write_app(scratch_modules, "staging_shop")

    compiled = _build("staging_shop", "staging")

    assert _echo(compiled) == EchoConfig(greeting="common", channels=("common", "staging"))


def test_a_folder_named_after_no_allowed_environment_is_refused(
    scratch_modules: ScratchModules,
) -> None:
    _write_app(scratch_modules, "typo_shop")
    scratch_modules.write({"typo_shop.config.packages.staing.echo": _NEEDS_A_DEV_DEPENDENCY})

    with pytest.raises(UnknownEnvironmentFolderError) as caught:
        _ = _build("typo_shop", "dev", allowed_envs=("dev", "test", "prod"))

    assert caught.value.folder == "typo_shop.config.packages.staing"
    assert caught.value.allowed == ("dev", "test", "prod")


def test_a_routes_folder_is_checked_like_a_packages_one(scratch_modules: ScratchModules) -> None:
    _write_app(scratch_modules, "routes_shop")
    scratch_modules.write({"routes_shop.config.routes.qa.extra": ""})

    with pytest.raises(UnknownEnvironmentFolderError, match=r"config\.routes\.qa"):
        _ = _build("routes_shop", "dev", allowed_envs=("dev", "prod"))


def test_without_allowed_envs_every_folder_is_an_environment(
    scratch_modules: ScratchModules,
) -> None:
    _write_app(scratch_modules, "open_shop")
    scratch_modules.write({"open_shop.config.packages.staing.echo": _NEEDS_A_DEV_DEPENDENCY})

    compiled = _build("open_shop", "dev")

    assert "open_shop.config.packages.staing" not in compiled.report.scan.modules
    assert ("open_shop.config.packages.staing", "environment folder for 'staing', not 'dev'") in (
        compiled.report.scan.skipped
    )


def test_a_module_beside_the_folders_is_common(scratch_modules: ScratchModules) -> None:
    _write_app(scratch_modules, "flat_shop")

    compiled = _build("flat_shop", "test")

    assert "flat_shop.config.packages.echo" in compiled.report.scan.modules
    assert _echo(compiled) == EchoConfig(greeting="common", channels=("common",))
