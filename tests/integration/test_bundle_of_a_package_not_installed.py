"""An application whose bundle list imports a development tool, built where the tool is absent.

The tool's package is never written: a deployment installs the runtime
dependencies only, while the application's bundle list imports every bundle it
lists, the tool's included. Built for ``prod``, where the list leaves the tool
disabled, the kernel boots without its package; built for ``dev``, where the
list activates it, the kernel says the package is missing.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, cast

import pytest

from xtr_dependency_injection import Kernel, KernelInterface
from xtr_dependency_injection.exception import MissingBundleError

if TYPE_CHECKING:
    from tests.support.modules import ScratchModules
    from xtr_dependency_injection.bundle.bundle import AnyBundle

pytestmark = pytest.mark.anyio

TOOLS = "acme_tools.bundle:ToolsBundle"

MAIL = """
from xtr_dependency_injection import Bundle, as_bundle


@as_bundle("mail")
class MailBundle(Bundle):
    pass
"""

APP_BUNDLES = """
from acme_mail.bundle import MailBundle
from acme_tools.bundle import ToolsBundle

BUNDLES = {
    MailBundle: {"all": True},
    ToolsBundle: {"dev": True},
}
"""

APP_BUNDLES_EVERYWHERE = """
from acme_tools.bundle import ToolsBundle

BUNDLES = {ToolsBundle: {"all": True}}
"""


@pytest.fixture
def application(scratch_modules: ScratchModules) -> ScratchModules:
    scratch_modules.write({"acme_mail.bundle": MAIL, "acme_shop.config.bundles": APP_BUNDLES})
    return scratch_modules


@pytest.mark.usefixtures("application")
async def test_it_boots_in_prod_without_the_tools_package() -> None:
    async with await Kernel("acme_shop", env="prod", environ={}).boot() as booted:
        info = await booted.container.get(KernelInterface)

    assert info.bundles == ("kernel", "mail")


@pytest.mark.usefixtures("application")
def test_it_reports_the_tools_bundle_disabled_in_prod() -> None:
    compiled = Kernel("acme_shop", env="prod", environ={}).build()

    (tools,) = [report for report in compiled.report.bundles if report.qualname == TOOLS]
    assert (tools.name, tools.source, tools.state) == (TOOLS, "listed", "env_disabled")


@pytest.mark.usefixtures("application")
def test_the_installed_bundle_beside_it_is_built_from_its_own_class() -> None:
    compiled = Kernel("acme_shop", env="prod", environ={}).build()

    # Written by the fixture, so only importable now.
    mail = cast("type[AnyBundle]", vars(importlib.import_module("acme_mail.bundle"))["MailBundle"])
    assert mail in {type(bundle) for bundle in compiled._bundles}


@pytest.mark.usefixtures("application")
def test_in_dev_it_names_the_bundle_whose_package_is_missing() -> None:
    with pytest.raises(MissingBundleError) as caught:
        _ = Kernel("acme_shop", env="dev", environ={}).build()

    assert caught.value.name == TOOLS


def test_a_bundle_listed_for_every_environment_is_refused_while_its_package_is_missing(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write({"acme_shop.config.bundles": APP_BUNDLES_EVERYWHERE})

    with pytest.raises(MissingBundleError) as caught:
        _ = Kernel("acme_shop", env="prod", environ={}).build()

    assert caught.value.name == TOOLS
