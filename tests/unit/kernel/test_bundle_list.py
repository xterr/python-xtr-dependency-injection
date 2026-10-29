from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING, cast

import pytest

from xtr_dependency_injection.bundle._absent_bundle import AbsentBundle
from xtr_dependency_injection.exception import ResourceImportError
from xtr_dependency_injection.kernel._bundle_list import load_bundle_list

if TYPE_CHECKING:
    from tests.support.modules import ScratchModules
    from xtr_dependency_injection.bundle.bundle import AnyBundle

_BUNDLES = "acme_shop.config.bundles"
_STAND_INS = {"acme_tools", "acme_tools.bundle"}

_MAIL = """
from xtr_dependency_injection import Bundle, as_bundle


@as_bundle("mail")
class MailBundle(Bundle):
    pass
"""

# The tools package comes first: the import that fails is the first one, so
# whatever follows is imported only once the list is read again.
_WITH_TOOLS = """
from acme_tools.bundle import ToolsBundle
from acme_mail.bundle import MailBundle

BUNDLES = {MailBundle: {"all": True}, ToolsBundle: {"dev": True}}
"""

_PROBE = """
try:
    import acme_optional
except ImportError:
    FOUND = False
else:
    FOUND = True
"""

_WITH_PROBE = """
from acme_tools.bundle import ToolsBundle
import acme_probe

BUNDLES = {ToolsBundle: {"dev": True}}
"""

_WITH_SERVICES = """
from acme_tools.bundle import ToolsBundle
import acme_shop.services

BUNDLES = {ToolsBundle: {"dev": True}}
"""

_SERVICES_NEEDING_A_TOOL = """
from acme_other_tool import Helper
"""

_WITH_A_MODULE_OF_ITS_OWN_MISSING = """
from acme_shop.not_there import Thing

BUNDLES = {}
"""

_WITH_A_MODULE_OF_AN_INSTALLED_PACKAGE_MISSING = """
from acme_mail.not_there import Thing

BUNDLES = {}
"""

_WITH_A_NAME_OF_AN_INSTALLED_MODULE_MISSING = """
from acme_mail.bundle import PostBundle

BUNDLES = {PostBundle: {"dev": True}}
"""


def _mail_bundle() -> type[AnyBundle]:
    # Written by the test, so only importable once it runs.
    return cast("type[AnyBundle]", vars(importlib.import_module("acme_mail.bundle"))["MailBundle"])


def test_a_bundle_imported_from_a_package_that_is_not_installed_is_listed_absent(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write({"acme_mail.bundle": _MAIL, _BUNDLES: _WITH_TOOLS})

    listed = load_bundle_list("acme_shop")

    assert listed[AbsentBundle("acme_tools.bundle", "ToolsBundle")] == {"dev": True}


def test_an_installed_bundle_beside_it_is_listed_as_its_own_class(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write({"acme_mail.bundle": _MAIL, _BUNDLES: _WITH_TOOLS})

    listed = load_bundle_list("acme_shop")

    assert listed[_mail_bundle()] == {"all": True}


def test_no_stand_in_is_left_importable_once_the_list_is_read(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write({"acme_mail.bundle": _MAIL, _BUNDLES: _WITH_TOOLS})

    _ = load_bundle_list("acme_shop")

    assert _STAND_INS.isdisjoint(sys.modules)


def test_the_import_system_is_left_as_it_was_once_the_list_is_read(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write({"acme_mail.bundle": _MAIL, _BUNDLES: _WITH_TOOLS})
    finders = list(sys.meta_path)

    _ = load_bundle_list("acme_shop")

    assert sys.meta_path == finders


def test_a_module_the_list_pulls_in_finds_only_what_is_installed(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write({"acme_probe": _PROBE, _BUNDLES: _WITH_PROBE})

    _ = load_bundle_list("acme_shop")

    assert vars(importlib.import_module("acme_probe"))["FOUND"] is False


def test_a_module_of_the_application_still_needs_every_package_it_imports(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write(
        {"acme_shop.services": _SERVICES_NEEDING_A_TOOL, _BUNDLES: _WITH_SERVICES}
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = load_bundle_list("acme_shop")

    assert caught.value.module == _BUNDLES


def test_no_stand_in_is_left_importable_when_the_list_still_fails(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write(
        {"acme_shop.services": _SERVICES_NEEDING_A_TOOL, _BUNDLES: _WITH_SERVICES}
    )

    with pytest.raises(ResourceImportError):
        _ = load_bundle_list("acme_shop")

    assert _STAND_INS.isdisjoint(sys.modules)


def test_the_import_system_is_left_as_it_was_when_the_list_still_fails(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write(
        {"acme_shop.services": _SERVICES_NEEDING_A_TOOL, _BUNDLES: _WITH_SERVICES}
    )
    finders = list(sys.meta_path)

    with pytest.raises(ResourceImportError):
        _ = load_bundle_list("acme_shop")

    assert sys.meta_path == finders


def test_a_module_missing_from_the_application_itself_is_not_stood_in(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write({_BUNDLES: _WITH_A_MODULE_OF_ITS_OWN_MISSING})

    with pytest.raises(ResourceImportError) as caught:
        _ = load_bundle_list("acme_shop")

    assert caught.value.module == _BUNDLES


def test_a_module_missing_from_an_installed_package_is_not_stood_in(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write(
        {"acme_mail.bundle": _MAIL, _BUNDLES: _WITH_A_MODULE_OF_AN_INSTALLED_PACKAGE_MISSING}
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = load_bundle_list("acme_shop")

    assert caught.value.module == _BUNDLES


def test_a_name_missing_from_an_installed_module_is_not_stood_in(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write(
        {"acme_mail.bundle": _MAIL, _BUNDLES: _WITH_A_NAME_OF_AN_INSTALLED_MODULE_MISSING}
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = load_bundle_list("acme_shop")

    assert caught.value.module == _BUNDLES
