"""An application with modules built on development-only packages, built where they are absent.

``acme_tools`` is a bundle the application lists for development and testing,
and ``acme_faker`` a development library: neither is written, as a deployment
installed without its development dependencies has neither. ``acme_claims`` is
installed, and its bundle registers, through its own autoconfiguration, every
class saying ``CLAIMED = True`` — as any library's bundle registers what it
recognises.
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, cast

import pytest

from xtr_dependency_injection import Kernel
from xtr_dependency_injection.exception import ResourceImportError, SetAsideModuleUsedError

if TYPE_CHECKING:
    from tests.support.modules import ScratchModules
    from xtr_dependency_injection.diagnostics import KernelReport

APP = "acme_app"

CLAIMS = """
from xtr_dependency_injection import Bundle, as_bundle


def _claimed(obj):
    return (obj,) if isinstance(obj, type) and vars(obj).get("CLAIMED") else ()


def _register(obj, item, services):
    _ = services.set(obj)


@as_bundle("claims")
class ClaimsBundle(Bundle):
    def build(self, builder):
        builder.register_attribute_for_autoconfiguration(_claimed, _register)
"""

BUNDLES = """
from acme_claims.bundle import ClaimsBundle
from acme_tools.bundle import ToolsBundle

BUNDLES = {ClaimsBundle: {"all": True}, ToolsBundle: {"dev": True, "test": True}}
"""

USER_FIXTURES = """
from acme_tools.fixtures import Fixture
import acme_faker

fake = acme_faker.Faker()


class UserFixtures(Fixture):
    name = fake.name()
"""

FAKE_HELPERS = """
import acme_faker


def fake_email() -> str:
    return acme_faker.Faker().email()
"""

REPORTS = """
class Reports:
    CLAIMED = True
"""


@pytest.fixture
def application(scratch_modules: ScratchModules) -> ScratchModules:
    scratch_modules.write(
        {
            "acme_claims.bundle": CLAIMS,
            f"{APP}.config.bundles": BUNDLES,
            f"{APP}.fixtures.users": USER_FIXTURES,
            f"{APP}.reports": REPORTS,
        }
    )
    return scratch_modules


def _build(env: str = "prod") -> KernelReport:
    return Kernel(APP, env=env, environ={}).build().report


@pytest.mark.usefixtures("application")
def test_a_reduced_install_builds_with_its_development_modules_set_aside() -> None:
    report = _build()

    assert [(entry.module, entry.missing) for entry in report.scan.set_aside] == [
        (f"{APP}.fixtures.users", ("acme_faker", "acme_tools")),
    ]
    assert f"{APP}.reports:Reports" in {d.provider_qualname for d in report.definitions}


@pytest.mark.usefixtures("application")
def test_the_scan_section_lists_what_was_set_aside() -> None:
    rendered = _build().render("scan")

    assert f"{APP}.fixtures.users  acme_faker, acme_tools  -" in rendered


@pytest.mark.usefixtures("application")
def test_building_twice_in_one_process_sets_aside_the_same_modules() -> None:
    first = _build()
    second = _build()

    assert second.scan.set_aside == first.scan.set_aside


@pytest.mark.usefixtures("application")
def test_the_build_says_what_it_set_aside(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="xtr_dependency_injection"):
        _ = _build()

    (record,) = caplog.records
    assert record.levelno == logging.INFO
    assert "Set aside 1 module(s)" in record.getMessage()
    assert "acme_faker, acme_tools" in record.getMessage()


def test_a_module_no_absent_bundle_explains_is_warned_of(
    application: ScratchModules, caplog: pytest.LogCaptureFixture
) -> None:
    application.write({f"{APP}.fake_helpers": FAKE_HELPERS})

    with caplog.at_level(logging.INFO, logger="xtr_dependency_injection"):
        _ = _build()

    (warning,) = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert f"{APP}.fake_helpers (needs acme_faker)" in warning.getMessage()
    assert f"{APP}.fixtures.users" not in warning.getMessage()


def test_a_set_aside_class_an_active_bundle_would_register_fails_the_build(
    application: ScratchModules,
) -> None:
    application.write(
        {f"{APP}.seed_reports": "import acme_faker\n\n\nclass SeedReports:\n    CLAIMED = True\n"}
    )

    with pytest.raises(SetAsideModuleUsedError) as caught:
        _ = _build()

    error = caught.value
    assert (error.name, error.use, error.missing) == (
        f"{APP}.seed_reports:SeedReports",
        "bundle 'claims' would register it",
        ("acme_faker",),
    )


def test_a_class_importing_a_set_aside_module_is_refused_through_it(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.seeded_reports": (
                f"from {APP}.fixtures.users import UserFixtures\n\n\n"
                "class SeededReports:\n    CLAIMED = True\n"
            )
        }
    )

    with pytest.raises(SetAsideModuleUsedError) as caught:
        _ = _build()

    assert caught.value.through == f"{APP}.fixtures.users"
    assert f"it imports {APP + '.fixtures.users'!r}, which needs" in str(caught.value)


def test_with_every_listed_bundle_active_a_module_needing_a_missing_package_is_refused(
    application: ScratchModules,
) -> None:
    application.write(
        {
            "acme_tools.bundle": (
                "from xtr_dependency_injection import Bundle, as_bundle\n\n\n"
                '@as_bundle("tools")\nclass ToolsBundle(Bundle):\n    pass\n'
            ),
            "acme_tools.fixtures": "class Fixture:\n    pass\n",
        }
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = _build("dev")

    assert caught.value.module == f"{APP}.fixtures.users"
    assert cast("ModuleNotFoundError", caught.value.__cause__).name == "acme_faker"


def test_a_bundle_disabled_here_lets_a_development_library_be_missing(
    application: ScratchModules, caplog: pytest.LogCaptureFixture
) -> None:
    # The tools bundle is installed, as a runtime dependency, and disabled in prod; the
    # fake-data library its fixtures use is a development one, so not installed.
    application.write(
        {
            "acme_tools.bundle": (
                "from xtr_dependency_injection import Bundle, as_bundle\n\n\n"
                '@as_bundle("tools")\nclass ToolsBundle(Bundle):\n    pass\n'
            ),
            "acme_tools.fixtures": "class Fixture:\n    pass\n",
        }
    )

    with caplog.at_level(logging.WARNING, logger="xtr_dependency_injection"):
        report = _build()

    assert [(e.module, e.missing, e.expected) for e in report.scan.set_aside] == [
        (f"{APP}.fixtures.users", ("acme_faker",), True),
    ]
    # It reaches the package of the tools bundle, disabled here: expected, nothing to warn of.
    assert caplog.records == []


def test_a_development_library_missing_for_an_active_bundle_fails_the_build(
    scratch_modules: ScratchModules,
) -> None:
    # Listed everywhere, installed as a runtime dependency; its fixtures still need a
    # development library, and another listed bundle is off here, so they are set aside —
    # and the active tools bundle would register them.
    scratch_modules.write(
        {
            "acme_claims.bundle": CLAIMS,
            "acme_tools.bundle": (
                "from xtr_dependency_injection import Bundle, as_bundle\n\n\n"
                '@as_bundle("tools")\nclass ToolsBundle(Bundle):\n    pass\n'
            ),
            f"{APP}.config.bundles": (
                "from acme_claims.bundle import ClaimsBundle\n"
                "from acme_tools.bundle import ToolsBundle\n\n"
                'BUNDLES = {ClaimsBundle: {"all": True}, ToolsBundle: {"dev": True}}\n'
            ),
            f"{APP}.seed": "import acme_faker\n\n\nclass Seed:\n    CLAIMED = True\n",
        }
    )

    with pytest.raises(SetAsideModuleUsedError) as caught:
        _ = _build()

    assert caught.value.use == "bundle 'claims' would register it"


DEV_TOOLS_BUNDLE = """
from xtr_dependency_injection import Bundle, as_bundle


@as_bundle("dev_tools", resources=("acme_app.dev_tools",))
class DevToolsBundle(Bundle):
    pass
"""

DEV_TOOLS = """
from acme_witness import RUNS

RUNS.append(__name__)


class Demo:
    CLAIMED = True
"""

DEV_TOOLS_BUNDLES = """
from acme_app.dev_bundle import DevToolsBundle
from acme_claims.bundle import ClaimsBundle

BUNDLES = {ClaimsBundle: {"all": True}, DevToolsBundle: {"dev": True}}
"""


@pytest.fixture
def dev_tools(scratch_modules: ScratchModules) -> ScratchModules:
    scratch_modules.write(
        {
            "acme_witness.__init__": "RUNS: list[str] = []\n",
            "acme_claims.bundle": CLAIMS,
            f"{APP}.config.bundles": DEV_TOOLS_BUNDLES,
            f"{APP}.dev_bundle": DEV_TOOLS_BUNDLE,
            f"{APP}.dev_tools.__init__": DEV_TOOLS,
        }
    )
    return scratch_modules


@pytest.mark.usefixtures("dev_tools")
def test_the_resources_of_an_inactive_listed_bundle_are_not_scanned() -> None:
    report = _build()

    assert f"{APP}.dev_tools" not in report.scan.modules
    assert cast("list[str]", importlib.import_module("acme_witness").RUNS) == []


@pytest.mark.usefixtures("dev_tools")
def test_the_resources_of_an_active_bundle_are_scanned() -> None:
    report = _build("dev")

    (demo,) = [d for d in report.definitions if d.provider_qualname == f"{APP}.dev_tools:Demo"]
    assert f"{APP}.dev_tools" in report.scan.modules
    assert cast("list[str]", importlib.import_module("acme_witness").RUNS) == [f"{APP}.dev_tools"]
    assert demo.origin.name == "claims"


def test_a_bundle_of_the_application_off_here_explains_only_its_own_subpackage(
    dev_tools: ScratchModules, caplog: pytest.LogCaptureFixture
) -> None:
    # The dev_tools bundle is the application's own, off in prod: what it explains is its
    # subpackage, not every module of the application — a faker-only helper is still warned of.
    dev_tools.write({f"{APP}.fake_helpers": FAKE_HELPERS})

    with caplog.at_level(logging.WARNING, logger="xtr_dependency_injection"):
        report = _build()

    assert [(e.module, e.expected) for e in report.scan.set_aside] == [
        (f"{APP}.fake_helpers", False),
    ]
    (warning,) = caplog.records
    assert f"{APP}.fake_helpers (needs acme_faker)" in warning.getMessage()


ROOT_BUNDLE = """
from xtr_dependency_injection import Bundle, as_bundle


@as_bundle("root_tools")
class RootToolsBundle(Bundle):
    pass
"""


def test_a_bundle_of_the_application_root_off_here_still_lets_modules_be_set_aside(
    scratch_modules: ScratchModules,
) -> None:
    # It explains no package — it owns no resources — but it is off here all the same.
    scratch_modules.write(
        {
            f"{APP}.__init__": ROOT_BUNDLE,
            f"{APP}.config.bundles": (
                f"from {APP} import RootToolsBundle\n\n"
                "BUNDLES = {RootToolsBundle: {'dev': True}}\n"
            ),
            f"{APP}.seed": "import acme_faker\n",
        }
    )

    report = _build()

    assert [(e.module, e.expected) for e in report.scan.set_aside] == [(f"{APP}.seed", False)]


SHOP_BUNDLE = """
from xtr_dependency_injection import Bundle, as_bundle


@as_bundle("shop", resources=("acme_app.shop",))
class ShopBundle(Bundle):
    pass
"""


def test_the_resources_of_an_active_application_bundle_are_the_applications_as_ever(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write(
        {
            "acme_claims.bundle": CLAIMS,
            f"{APP}.shop_bundle": SHOP_BUNDLE,
            f"{APP}.config.bundles": (
                "from acme_claims.bundle import ClaimsBundle\n"
                f"from {APP}.shop_bundle import ShopBundle\n\n"
                "BUNDLES = {ClaimsBundle: {'all': True}, ShopBundle: {'all': True}}\n"
            ),
            f"{APP}.shop": (
                "from xtr_dependency_injection import as_service\n\n\n"
                "@as_service\nclass ShopMailer:\n    pass\n"
            ),
        }
    )

    report = _build()

    (mailer,) = [d for d in report.definitions if d.provider_qualname == f"{APP}.shop:ShopMailer"]
    assert mailer.origin.kind == "app"


TRACED_CLAIMS = """
from xtr_dependency_injection import Bundle, as_bundle

from xtr_dependency_injection.scan._stand_ins import StandIn


def _held(obj):
    # A reader recognising only what a module holds as is: a marker put over a stand-in.
    return (obj,) if isinstance(obj, StandIn) and getattr(obj, "CLAIMED", False) else ()


def _register(obj, item, services):
    raise AssertionError("never registered")


@as_bundle("claims")
class ClaimsBundle(Bundle):
    def build(self, builder):
        builder.register_attribute_for_autoconfiguration(_held, _register)
"""


def test_a_marker_put_over_a_stand_in_decorator_is_refused_rather_than_dropped(
    application: ScratchModules,
) -> None:
    application.write(
        {
            "acme_claims.bundle": TRACED_CLAIMS,
            f"{APP}.seed_command": (
                "import acme_faker\n\n\n@acme_faker.traced\ndef seed():\n    pass\n\n\n"
                "seed.CLAIMED = True\n"
            ),
        }
    )

    with pytest.raises(SetAsideModuleUsedError) as caught:
        _ = _build()

    assert caught.value.name == f"{APP}.seed_command:seed"


def test_a_module_a_set_aside_package_imports_is_refused_where_a_bundle_would_register_it(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.seeds.__init__": (
                f"import acme_faker\n\nfake = acme_faker.Faker()\n\nfrom {APP}.seeds import plain\n"
            ),
            f"{APP}.seeds.plain": (
                f"from {APP}.seeds import fake\n\n\nclass Plain:\n    CLAIMED = True\n"
                "    NAME = fake.name()\n"
            ),
        }
    )

    with pytest.raises(SetAsideModuleUsedError) as caught:
        _ = _build()

    assert (caught.value.name, caught.value.through) == (f"{APP}.seeds.plain:Plain", f"{APP}.seeds")


def test_a_re_exporting_fixtures_package_with_a_healthy_module_boots_running_it_once(
    application: ScratchModules,
) -> None:
    # The package loads a healthy module, then its fixtures; one of those imports another
    # through the package. Another module imports the package again, truthfully.
    application.write(
        {
            "acme_witness.__init__": "RUNS: list[str] = []\n",
            f"{APP}.fixtures.__init__": (
                "from .load import load\nfrom .users import UserFixtures\n"
                "from .orders import OrderFixtures\n"
            ),
            f"{APP}.fixtures.load": (
                "from acme_witness import RUNS\n\nRUNS.append(__name__)\n\n\n"
                "def load():\n    pass\n"
            ),
            f"{APP}.fixtures.orders": (
                "from acme_tools.fixtures import Fixture\n"
                f"from {APP}.fixtures import UserFixtures\n\n\n"
                "class OrderFixtures(Fixture):\n    after = UserFixtures\n"
            ),
            f"{APP}.seeding": f"from {APP}.fixtures.orders import OrderFixtures\n",
        }
    )

    report = _build()

    assert {f"{APP}.fixtures", f"{APP}.fixtures.orders", f"{APP}.seeding"} <= {
        entry.module for entry in report.scan.set_aside
    }
    assert cast("list[str]", importlib.import_module("acme_witness").RUNS) == [
        f"{APP}.fixtures.load"
    ]
