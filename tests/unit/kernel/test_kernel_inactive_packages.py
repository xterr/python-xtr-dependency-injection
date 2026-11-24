"""Which packages a listed bundle that is not active stands for, for set-aside modules."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from xtr_dependency_injection import Bundle, as_bundle
from xtr_dependency_injection.bundle._absent_bundle import AbsentBundle
from xtr_dependency_injection.diagnostics import BundleReport
from xtr_dependency_injection.exception._naming import qualified_name
from xtr_dependency_injection.kernel.kernel import _inactive_packages, _own_package

if TYPE_CHECKING:
    from xtr_dependency_injection.bundle.bundle import AnyBundle
    from xtr_dependency_injection.bundle.bundle_resolver import ListedBundles


def _report(qualname: str, state: str = "env_disabled") -> BundleReport:
    return BundleReport(qualname, qualname, "listed", state)  # pyright: ignore[reportArgumentType] — a state the test picks  # ty: ignore[invalid-argument-type]


def _bundle(module: str, name: str, resources: tuple[str, ...] = ()) -> type[AnyBundle]:
    cls = type(name, (Bundle,), {"__module__": module})
    return as_bundle(name.lower(), resources=resources)(cls)


@pytest.mark.parametrize(
    ("module", "application", "package"),
    [
        ("acme_tools.bundle", "acme_app", "acme_tools"),
        ("company.tools.bundle", "company.shop", "company.tools"),
        ("company.shop_tools.bundle", "company.shop", "company.shop_tools"),
        ("acme_tools.bundle", "", "acme_tools"),
    ],
)
def test_a_bundle_from_elsewhere_stands_for_the_first_package_holding_no_application(
    module: str, application: str, package: str
) -> None:
    assert _own_package(module, application) == package


def test_an_absent_bundle_stands_for_its_package() -> None:
    absent = AbsentBundle("acme_tools.bundle", "ToolsBundle")
    listed: ListedBundles = {absent: {"dev": True}}

    assert _inactive_packages([_report(absent.target)], listed, "acme_app") == ("acme_tools",)


def test_an_active_bundle_stands_for_nothing() -> None:
    absent = AbsentBundle("acme_tools.bundle", "ToolsBundle")
    listed: ListedBundles = {absent: {"all": True}}

    assert _inactive_packages([_report(absent.target, "active")], listed, "acme_app") == ()


def test_an_application_bundle_stands_for_its_module_and_its_resources() -> None:
    bundle = _bundle("acme_app.bundle.dev_bundle", "DevBundle", ("acme_app.dev_tools",))
    listed: ListedBundles = {bundle: {"dev": True}}

    found = _inactive_packages([_report(qualified_name(bundle))], listed, "acme_app")

    assert found == ("acme_app.bundle.dev_bundle", "acme_app.dev_tools")


def test_an_application_bundle_in_its_root_module_stands_for_its_resources_alone() -> None:
    bundle = _bundle("acme_app", "RootBundle")
    listed: ListedBundles = {bundle: {"dev": True}}

    assert _inactive_packages([_report(qualified_name(bundle))], listed, "acme_app") == ()


def test_a_bundle_in_a_namespace_the_application_lies_in_stands_for_nothing_of_it() -> None:
    absent = AbsentBundle("company", "CompanyBundle")
    listed: ListedBundles = {absent: {"dev": True}}

    assert _inactive_packages([_report(absent.target)], listed, "company.shop") == ()
