"""The application scan where a listed bundle is not active, setting aside what cannot import.

``acme_tools`` stands for an inactive listed bundle's package and ``acme_faker``
for a development library: neither is ever written, so neither is installed.
``acme_witness`` is installed, and counts how many times a module ran.
"""

from __future__ import annotations

import builtins
import gc
import importlib
import importlib.util
import sys
from typing import TYPE_CHECKING, cast

import pytest

from tests.support.set_aside import violations
from xtr_dependency_injection.exception import ResourceImportError, SetAsideModuleUsedError
from xtr_dependency_injection.scan import DEFAULT_EXCLUDES
from xtr_dependency_injection.scan._refusal import RefusalFinder
from xtr_dependency_injection.scan._stand_ins import StandIn, unwrapped
from xtr_dependency_injection.scan.scanner import Scanner

if TYPE_CHECKING:
    from tests.support.modules import ScratchModules
    from xtr_dependency_injection.scan.scanner import ScanResult

APP = "acme_app"

FIXTURES = """
from acme_tools.fixtures import Fixture
import acme_faker
from acme_witness import RUNS

RUNS.append(__name__)
fake = acme_faker.Faker("en_US")


class UserFixtures(Fixture):
    name = fake.name()


@acme_faker.register
class Registered:
    pass


def helper() -> None: ...
"""

SERVICES = """
class Plain:
    pass
"""

SEEDING = """
from acme_app.fixtures.users import UserFixtures


class Seeder:
    pass
"""


def _scanner(*, inactive: tuple[str, ...] = ("acme_tools",), env: str = "prod") -> Scanner:
    return Scanner(env=env, exclude=DEFAULT_EXCLUDES, package=APP, inactive_packages=inactive)


def _scan(scanner: Scanner | None = None) -> tuple[Scanner, ScanResult]:
    """Scan the application; whether it fails or not, nothing untruthful is left behind."""
    scanner = scanner or _scanner()
    before = frozenset(sys.modules)
    meta_path, import_function = cast("list[object]", list(sys.meta_path)), builtins.__import__
    result: ScanResult | None = None
    try:
        result = scanner.scan([APP], owner=None)
    finally:
        left = violations(
            scanner,
            result,
            loaded_before=before,
            meta_path=meta_path,
            import_function=import_function,
        )
        assert left == []
    assert result is not None
    return scanner, result


def _runs() -> list[str]:
    return cast("list[str]", importlib.import_module("acme_witness").RUNS)


def _set_aside(scanner: Scanner) -> dict[str, tuple[tuple[str, ...], str | None]]:
    return {entry.module: (entry.missing, entry.through) for entry in scanner.set_aside}


def _services(result: ScanResult) -> list[str]:
    return [scanned.name for scanned in result.services]


@pytest.fixture
def application(scratch_modules: ScratchModules) -> ScratchModules:
    scratch_modules.write(
        {
            "acme_witness.__init__": "RUNS: list[str] = []\n",
            f"{APP}.__init__": "",
            f"{APP}.fixtures.users": FIXTURES,
            f"{APP}.services": SERVICES,
            f"{APP}.seeding": SEEDING,
        }
    )
    return scratch_modules


# --- where every listed bundle is active ---------------------------------------------


@pytest.mark.usefixtures("application")
def test_every_failed_import_is_fatal_where_every_listed_bundle_is_active() -> None:
    with pytest.raises(ResourceImportError) as caught:
        _ = _scan(_scanner(inactive=()))

    assert caught.value.module == f"{APP}.fixtures.users"
    assert isinstance(caught.value.__cause__, ModuleNotFoundError)


# --- what is set aside ---------------------------------------------------------------


@pytest.mark.usefixtures("application")
def test_a_module_needing_packages_not_installed_is_set_aside() -> None:
    scanner, result = _scan()

    assert _set_aside(scanner)[f"{APP}.fixtures.users"] == (("acme_faker", "acme_tools"), None)
    # A decorated class is listed twice: itself, and the stand-in the module holds in its place.
    assert [scanned.name for scanned in result.set_aside] == [
        f"{APP}.fixtures.users:UserFixtures",
        f"{APP}.fixtures.users:Registered",
        f"{APP}.fixtures.users:Registered",
        f"{APP}.fixtures.users:helper",
        f"{APP}.seeding:Seeder",
    ]


@pytest.mark.usefixtures("application")
def test_nothing_set_aside_becomes_a_candidate() -> None:
    _, result = _scan()

    assert _services(result) == [f"{APP}.services:Plain"]


@pytest.mark.usefixtures("application")
def test_a_class_a_stand_in_decorates_stays_what_the_module_defines() -> None:
    scanner, _ = _scan()

    (users,) = [entry for entry in scanner.set_aside if entry.module == f"{APP}.fixtures.users"]
    assert users.defines == (
        f"{APP}.fixtures.users:UserFixtures",
        f"{APP}.fixtures.users:Registered",
        f"{APP}.fixtures.users:helper",
    )


@pytest.mark.usefixtures("application")
def test_a_module_importing_a_set_aside_module_is_set_aside_through_it() -> None:
    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.seeding"] == (
        ("acme_faker", "acme_tools"),
        f"{APP}.fixtures.users",
    )


def test_a_set_aside_module_runs_once_more_whichever_imports_it_first(
    application: ScratchModules,
) -> None:
    application.write({f"{APP}.aa_seeding": SEEDING})

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.aa_seeding"][1] == f"{APP}.fixtures.users"
    # Once when inspected for aa_seeding; never again — not for its own turn, nor for seeding.
    assert _runs() == [f"{APP}.fixtures.users"]


def test_a_module_importing_a_class_a_stand_in_decorated_is_set_aside_through_its_module(
    application: ScratchModules,
) -> None:
    application.write({f"{APP}.zz_reports": f"from {APP}.fixtures.users import Registered\n"})

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.zz_reports"][1] == f"{APP}.fixtures.users"


def test_the_modules_of_a_set_aside_package_are_set_aside_through_it(
    application: ScratchModules,
) -> None:
    application.write(
        {f"{APP}.seeds.__init__": "import acme_faker\n", f"{APP}.seeds.users": SERVICES}
    )

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.seeds.users"] == (("acme_faker",), f"{APP}.seeds")


def test_each_package_a_module_turns_out_to_need_is_stood_in_for(
    application: ScratchModules,
) -> None:
    application.write(
        {f"{APP}.two": "import acme_faker\nimport acme_factories\n\n\nclass Two:\n    pass\n"}
    )

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.two"] == (("acme_factories", "acme_faker"), None)


# --- however it reached the missing package ------------------------------------------


def test_a_module_reaching_the_missing_package_through_a_function_it_calls_fails_naming_it(
    application: ScratchModules,
) -> None:
    # Only the module's own import statements are served: the helper imports for itself.
    application.write(
        {
            f"{APP}.aa_util": "def make():\n    import acme_faker\n    return acme_faker.Faker()\n",
            f"{APP}.zz_seed": (
                f"from {APP}.aa_util import make\n\nFAKE = make()\n\n\n"
                "class Seeder:\n    def name(self):\n        return FAKE.name()\n"
            ),
        }
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.zz_seed"
    (note,) = caught.value.__notes__
    assert f"not to an import statement of {APP}.aa_util:make" in note
    assert f"{APP}.aa_util" in sys.modules


def test_a_module_importing_the_missing_package_with_importlib_fails_saying_so(
    application: ScratchModules,
) -> None:
    application.write(
        {f"{APP}.dynamic": "import importlib\n\nfaker = importlib.import_module('acme_faker')\n"}
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    (note,) = caught.value.__notes__
    assert f"not to importlib.import_module, called by {APP}.dynamic:<module>" in note


def test_a_module_importing_a_set_aside_module_with_importlib_fails_saying_so(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.zz_loader": (
                f"import importlib\n\nusers = importlib.import_module('{APP}.fixtures.users')\n\n\n"
                "class Loader:\n    pass\n"
            )
        }
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.zz_loader"
    (note,) = caught.value.__notes__
    served = f"'{APP}.fixtures.users' is served only to this module's own import statements"
    assert note.endswith(
        f"{served} — not to importlib.import_module, called by {APP}.zz_loader:<module>"
    )


def test_a_helper_importing_a_set_aside_module_for_a_set_aside_one_is_named(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.bb_util": (
                f"def users():\n    from {APP}.fixtures import users\n    return users\n"
            ),
            f"{APP}.zz_seed": (
                f"import acme_faker\nfrom {APP}.bb_util import users\n\nU = users()\n"
            ),
        }
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    (note,) = caught.value.__notes__
    assert note.endswith(f"not to an import statement of {APP}.bb_util:users")


def test_a_failure_raised_by_a_module_a_set_aside_one_imports_names_where(
    application: ScratchModules,
) -> None:
    application.write(
        {
            "acme_side.__init__": "raise RuntimeError('side effect')\n",
            f"{APP}.zz_fx": "import acme_faker\nimport acme_side\n",
        }
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    (note,) = caught.value.__notes__
    assert note.endswith("; raised in acme_side:<module>")


# --- what is kept --------------------------------------------------------------------


def test_a_module_first_imported_by_a_set_aside_one_is_scanned_as_ever_and_runs_once(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.aa_seed": f"import acme_faker\nfrom {APP}.zz_models import User\n",
            f"{APP}.zz_models": (
                "from acme_witness import RUNS\n\nRUNS.append(__name__)\n\n\n"
                "class User:\n    pass\n"
            ),
        }
    )

    scanner, result = _scan()

    assert f"{APP}.zz_models" not in _set_aside(scanner)
    assert f"{APP}.zz_models:User" in _services(result)
    assert _runs().count(f"{APP}.zz_models") == 1


@pytest.mark.parametrize("prober", ["aa_text", "zz_text"])
def test_a_module_probing_for_a_missing_package_is_kept_whatever_its_order(
    application: ScratchModules, prober: str
) -> None:
    application.write(
        {
            f"{APP}.mm_seed": f"import acme_faker\nfrom {APP}.{prober} import Slugger\n",
            f"{APP}.{prober}": (
                "try:\n    import acme_faker\nexcept ImportError:\n    acme_faker = None\n\n\n"
                "class Slugger:\n    FAKER = acme_faker\n"
            ),
        }
    )

    scanner, result = _scan()

    assert f"{APP}.{prober}" not in _set_aside(scanner)
    assert f"{APP}.{prober}:Slugger" in _services(result)
    slugger = cast("type", vars(sys.modules[f"{APP}.{prober}"])["Slugger"])
    assert vars(slugger)["FAKER"] is None


@pytest.mark.parametrize("service", ["aa_service", "zz_service"])
def test_a_module_importing_a_set_aside_one_optionally_is_kept_whatever_its_order(
    application: ScratchModules, service: str
) -> None:
    application.write(
        {
            f"{APP}.{service}": (
                f"try:\n    from {APP}.fixtures.users import UserFixtures\n"
                "except ImportError:\n    UserFixtures = None\n\n\nclass Svc:\n    pass\n"
            )
        }
    )

    scanner, result = _scan()

    assert f"{APP}.{service}" not in _set_aside(scanner)
    assert f"{APP}.{service}:Svc" in _services(result)


def test_an_installed_library_probing_while_inspected_is_imported_again_truthfully(
    application: ScratchModules,
) -> None:
    application.write(
        {
            "acme_probe.__init__": (
                "import importlib.util\n\n"
                "HAS_FAKER = importlib.util.find_spec('acme_faker') is not None\n"
            ),
            f"{APP}.aa_seed": "import acme_faker\nimport acme_probe\n",
            f"{APP}.zz_uses_probe": "import acme_probe\n\n\nclass Uses:\n    pass\n",
        }
    )

    scanner, result = _scan()

    probe = importlib.import_module("acme_probe")
    assert cast("bool", probe.HAS_FAKER) is False
    assert f"{APP}.zz_uses_probe:Uses" in _services(result)
    assert f"{APP}.zz_uses_probe" not in _set_aside(scanner)


def test_an_installed_library_needing_a_missing_package_is_dropped(
    application: ScratchModules,
) -> None:
    application.write(
        {
            "acme_lib.__init__": "import acme_faker\n\n\nclass Client:\n    pass\n",
            f"{APP}.uses_lib": "import acme_lib\n",
        }
    )

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.uses_lib"] == (("acme_faker",), "acme_lib")
    assert "acme_lib" not in sys.modules


def test_a_probing_module_imported_between_inspections_is_kept_truthful(
    application: ScratchModules,
) -> None:
    probe = "try:\n    import acme_faker\nexcept ImportError:\n    acme_faker = None\n"
    application.write(
        {
            f"{APP}.b_seed": f"import acme_faker\nimport {APP}.p_probe\n",
            f"{APP}.c_user": f"from {APP}.p_probe import acme_faker as probed\n",
            f"{APP}.d_seed": f"import acme_faker\nimport {APP}.p_probe\n",
            f"{APP}.p_probe": probe,
        }
    )

    scanner, _ = _scan()

    assert {f"{APP}.b_seed", f"{APP}.d_seed"} <= set(_set_aside(scanner))
    assert f"{APP}.p_probe" not in _set_aside(scanner)
    assert f"{APP}.c_user" not in _set_aside(scanner)
    assert vars(sys.modules[f"{APP}.p_probe"])["acme_faker"] is None


REGISTRY = """
NAMES: list[str] = []


def register(name):
    if name in NAMES:
        raise RuntimeError(f"{name} already registered")
    NAMES.append(name)
"""


@pytest.mark.parametrize("seed", ["aa_seed", "zz_seed"])
def test_a_module_behind_a_probing_library_runs_once_whatever_the_order(
    application: ScratchModules, seed: str
) -> None:
    # An installed library probing for the package a fixture needs, imported first by that
    # fixture's inspection, and a module registering with a library that refuses twice.
    application.write(
        {
            "acme_registry.__init__": REGISTRY,
            "acme_probing.__init__": (
                "try:\n    import acme_faker\nexcept ImportError:\n    acme_faker = None\n"
            ),
            f"{APP}.mm_models": (
                "import acme_probing\nimport acme_registry\n\n"
                "acme_registry.register('users')\n\n\nclass User:\n    pass\n"
            ),
            f"{APP}.{seed}": f"import acme_faker\nfrom {APP}.mm_models import User\n",
        }
    )

    scanner, result = _scan()

    assert f"{APP}.mm_models:User" in _services(result)
    assert f"{APP}.{seed}" in _set_aside(scanner)
    assert cast("list[str]", importlib.import_module("acme_registry").NAMES) == ["users"]
    assert vars(importlib.import_module("acme_probing"))["acme_faker"] is None


def test_a_module_reaching_a_set_aside_one_through_another_is_set_aside_through_that(
    application: ScratchModules,
) -> None:
    # aa_seed is inspected first; mm_mid, run truthfully for it, imports the fixtures.
    application.write(
        {
            f"{APP}.aa_seed": f"import acme_faker\nimport {APP}.mm_mid\n",
            f"{APP}.mm_mid": f"from {APP}.fixtures.users import UserFixtures\n",
        }
    )

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.mm_mid"][1] == f"{APP}.fixtures.users"
    assert _runs() == [f"{APP}.fixtures.users"]


def test_a_set_aside_module_imported_twice_by_one_module_is_served_twice(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.zz_twice": (
                f"import {APP}.fixtures.users\nfrom {APP}.fixtures.users import UserFixtures\n"
            )
        }
    )

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.zz_twice"][1] == f"{APP}.fixtures.users"


def test_modules_needing_each_other_and_a_missing_package_are_both_set_aside(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.aa_one": f"import acme_faker\nimport {APP}.bb_two\n",
            f"{APP}.bb_two": f"import {APP}.aa_one\nimport acme_faker\n",
        }
    )

    scanner, _ = _scan()

    set_aside = _set_aside(scanner)
    assert set_aside[f"{APP}.aa_one"] == (("acme_faker",), None)
    assert set_aside[f"{APP}.bb_two"] == (("acme_faker",), None)


def test_an_import_error_for_no_missing_module_stays_fatal(application: ScratchModules) -> None:
    application.write({f"{APP}.broken": "import acme_faker\nfrom json import not_there\n"})

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.broken"


def test_an_import_error_raised_over_nothing_missing_stays_fatal(
    application: ScratchModules,
) -> None:
    application.write({f"{APP}.broken": "import acme_faker\nraise ImportError('no extra')\n"})

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.broken"


def test_a_module_reaching_faker_through_a_helper_inside_another_inspection_fails_naming_it(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.aa_util": "def make():\n    import acme_faker\n    return acme_faker.Faker()\n",
            f"{APP}.bb_seed": f"import acme_faker\nfrom {APP}.zz_svc import Svc\n",
            f"{APP}.zz_svc": (
                f"from {APP}.aa_util import make\n\nFAKES = [make()]\n\n\n"
                "class Svc:\n    names = FAKES\n"
            ),
        }
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.zz_svc"
    (note,) = caught.value.__notes__
    assert f"not to an import statement of {APP}.aa_util:make" in note


def test_a_lazy_object_in_a_module_imported_while_inspecting_is_left_alone(
    application: ScratchModules,
) -> None:
    application.write(
        {
            "acme_lazy.__init__": (
                "class _Lazy:\n    @property\n    def __class__(self):\n"
                "        raise RuntimeError('not configured')\n\n\nsettings = _Lazy()\n"
            ),
            f"{APP}.aa_seed": "import acme_faker\nimport acme_lazy\n",
        }
    )

    scanner, _ = _scan()

    assert f"{APP}.aa_seed" in _set_aside(scanner)
    assert "acme_lazy" in sys.modules


def test_an_import_error_raised_over_a_missing_package_is_read_through(
    application: ScratchModules,
) -> None:
    application.write(
        {
            "acme_extra.__init__": (
                "try:\n    import acme_faker\nexcept ModuleNotFoundError as error:\n"
                "    raise ImportError('install acme_extra[fake]') from error\n"
            ),
            f"{APP}.uses_extra": "import acme_extra\n",
        }
    )

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.uses_extra"] == (("acme_faker",), "acme_extra")
    assert "acme_extra" not in sys.modules


@pytest.mark.usefixtures("application")
def test_a_set_aside_module_named_again_as_a_root_is_not_imported_again() -> None:
    scanner = _scanner()

    _ = scanner.scan([APP, f"{APP}.fixtures.users"], owner=None)

    assert _runs() == [f"{APP}.fixtures.users"]


# --- stand-ins, as fixture code uses them ---------------------------------------------


def test_a_decorator_factory_handed_a_class_keeps_both_classes(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.depends": (
                "import acme_tools.fixtures as f\n\n\n"
                "class Users(f.Fixture):\n    pass\n\n\n"
                "@f.depends_on(Users)\nclass Orders(f.Fixture):\n    pass\n\n\n"
                "def users():\n    pass\n\n\n"
                "@f.after(users)\ndef orders():\n    pass\n"
            )
        }
    )

    scanner, _ = _scan()

    (entry,) = [e for e in scanner.set_aside if e.module == f"{APP}.depends"]
    assert entry.defines == (
        f"{APP}.depends:Users",
        f"{APP}.depends:Orders",
        f"{APP}.depends:users",
        f"{APP}.depends:orders",
    )


def test_a_class_built_by_a_stand_in_metaclass_is_what_the_module_defines(
    application: ScratchModules,
) -> None:
    application.write(
        {f"{APP}.meta": "import acme_faker\n\n\nclass Model(metaclass=acme_faker.Meta): ...\n"}
    )

    scanner, _ = _scan()

    (entry,) = [e for e in scanner.set_aside if e.module == f"{APP}.meta"]
    assert entry.defines == (f"{APP}.meta:Model",)


def test_module_level_code_computing_with_fake_values_runs_through(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.computed": (
                "import acme_faker\n\n"
                "fake = acme_faker.Faker()\n"
                "AGE = fake.random_int() + 1\nCOUNT = len(fake.names())\n"
                "FIRST = [1][fake.index()]\n"
                "IS = isinstance(1, acme_faker.Model)\n"
                "with fake.context():\n    pass\n"
                "fake.seed = 4\n"
                "if fake.random_int() > 3:\n    pass\n"
            )
        }
    )

    scanner, _ = _scan()

    assert f"{APP}.computed" in _set_aside(scanner)


def test_a_module_handing_a_stand_in_to_an_installed_library_is_fatal_naming_its_package(
    application: ScratchModules,
) -> None:
    application.write(
        {f"{APP}.dumped": "import json\nimport acme_faker\n\nDUMP = json.dumps(acme_faker.data)\n"}
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.dumped"
    assert isinstance(caught.value.__cause__, TypeError)
    # Only what this module needs: acme_tools, missing for the fixtures scanned before it, is not.
    (note,) = caught.value.__notes__
    assert note.startswith("imported again with 'acme_faker' stood in for — not installed here")


# --- expected or not -----------------------------------------------------------------


def test_a_module_reaching_an_inactive_bundles_package_is_expected(
    application: ScratchModules,
) -> None:
    # acme_tools stands for an inactive bundle installed beside the application here.
    application.write(
        {
            "acme_tools.__init__": "",
            "acme_tools.fixtures": "class Fixture:\n    pass\n",
            f"{APP}.helper": "import acme_faker\n",
        }
    )

    scanner, _ = _scan()

    expected = {entry.module: entry.expected for entry in scanner.set_aside}
    assert expected[f"{APP}.fixtures.users"] is True
    assert expected[f"{APP}.seeding"] is True
    assert expected[f"{APP}.helper"] is False


# --- what stays fatal ----------------------------------------------------------------


def test_a_module_missing_from_the_application_stays_fatal(application: ScratchModules) -> None:
    application.write({f"{APP}.broken": f"import {APP}.not_there\n"})

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.broken"


def test_a_module_missing_from_an_installed_package_stays_fatal(
    application: ScratchModules,
) -> None:
    application.write({f"{APP}.broken": "import acme_witness.not_there\n"})

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.broken"


def test_a_module_failing_otherwise_stays_fatal(application: ScratchModules) -> None:
    application.write({f"{APP}.broken": "import acme_faker\nraise RuntimeError('broken')\n"})

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert isinstance(caught.value.__cause__, RuntimeError)


def test_a_missing_module_error_naming_no_module_stays_fatal(
    application: ScratchModules,
) -> None:
    application.write({f"{APP}.broken": "raise ModuleNotFoundError('no name given')\n"})

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.broken"


def test_a_module_failing_otherwise_before_any_missing_import_stays_fatal(
    application: ScratchModules,
) -> None:
    application.write({f"{APP}.broken": "raise RuntimeError('broken')\n"})

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert isinstance(caught.value.__cause__, RuntimeError)


def test_a_module_also_missing_from_the_application_stays_fatal_once_inspected(
    application: ScratchModules,
) -> None:
    application.write({f"{APP}.broken": f"import acme_faker\nimport {APP}.not_there\n"})

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert cast("ModuleNotFoundError", caught.value.__cause__).name == f"{APP}.not_there"


@pytest.mark.usefixtures("application")
def test_a_bundle_resource_scan_stays_strict() -> None:
    with pytest.raises(ResourceImportError):
        _ = _scanner().scan([f"{APP}.fixtures"], owner="tools")


# --- what would be used ---------------------------------------------------------------

_SERVICE = "from xtr_dependency_injection import as_service\n\n\n@as_service\nclass Mailer: ...\n"
_HOOK = "from xtr_dependency_injection import on_boot\n\n\n@on_boot\nasync def warm(): ...\n"
_ALIAS = (
    "from xtr_dependency_injection import as_alias\n\n\nclass Iface:\n    pass\n\n\n"
    "@as_alias(Iface)\nclass Mailer(Iface):\n    pass\n"
)
_SERVICE_OVER_A_STAND_IN = (
    "from xtr_dependency_injection import as_service\n\n\n"
    "@as_service\n@acme_faker.register\nclass Mailer:\n    pass\n"
)
_SERVICE_OVER_STACKED_STAND_INS = (
    "from xtr_dependency_injection import as_service\n\n\n"
    "@as_service\n@acme_faker.register\n@acme_faker.other\nclass Mailer:\n    pass\n"
)
_TAGGED_ITEM = (
    "from xtr_dependency_injection import as_tagged_item\n\n\n"
    "@as_tagged_item(priority=1)\nclass Mailer:\n    pass\n"
)
_AUTOCONFIGURE = (
    "from xtr_dependency_injection import autoconfigure\n\n\n"
    "@autoconfigure(tags=('mailer',))\nclass Mailer:\n    pass\n"
)
_AUTOCONFIGURE_TAG = (
    "from xtr_dependency_injection import autoconfigure_tag\n\n\n"
    "@autoconfigure_tag('mailer')\nclass Mailer:\n    pass\n"
)


@pytest.mark.parametrize(
    ("source", "use"),
    [
        (_SERVICE, "@as_service"),
        (_HOOK, "@on_boot"),
        (_ALIAS, "@as_alias"),
        (_SERVICE_OVER_A_STAND_IN, "@as_service"),
        (_SERVICE_OVER_STACKED_STAND_INS, "@as_service"),
        (_TAGGED_ITEM, "@as_tagged_item"),
        (_AUTOCONFIGURE, "@autoconfigure"),
        (_AUTOCONFIGURE_TAG, "@autoconfigure_tag"),
    ],
    ids=[
        "service",
        "hook",
        "alias",
        "service-over-a-stand-in-decorator",
        "service-over-stacked-stand-in-decorators",
        "tagged-item",
        "autoconfigure",
        "autoconfigure-tag",
    ],
)
def test_a_set_aside_object_carrying_a_marker_fails_the_scan(
    application: ScratchModules, source: str, use: str
) -> None:
    application.write({f"{APP}.marked": f"import acme_faker\n{source}"})

    with pytest.raises(SetAsideModuleUsedError) as caught:
        _ = _scan()

    assert (caught.value.module, caught.value.use, caught.value.missing) == (
        f"{APP}.marked",
        use,
        ("acme_faker",),
    )


def test_a_set_aside_service_of_another_environment_is_only_skipped(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.mailer": (
                "from xtr_dependency_injection import as_service, when\nimport acme_faker\n\n\n"
                '@when("dev")\n@as_service\nclass Mailer:\n    pass\n'
            )
        }
    )

    scanner, _ = _scan()

    assert (f"{APP}.mailer:Mailer", "@when(dev) excludes 'prod'") in scanner.skipped


def test_an_excluded_set_aside_service_is_ignored(application: ScratchModules) -> None:
    application.write(
        {
            f"{APP}.mailer": (
                "from xtr_dependency_injection import as_service, exclude\nimport acme_faker\n\n\n"
                "@exclude\n@as_service\nclass Mailer:\n    pass\n"
            )
        }
    )

    scanner, _ = _scan()

    assert f"{APP}.mailer" in _set_aside(scanner)


# --- what the scan leaves behind -----------------------------------------------------


@pytest.mark.usefixtures("application")
def test_set_aside_modules_are_not_scanned_modules() -> None:
    scanner, _ = _scan()

    assert scanner.modules == [APP, f"{APP}.fixtures", f"{APP}.services"]


@pytest.mark.usefixtures("application")
def test_set_aside_modules_are_not_loaded_once_the_scan_ends() -> None:
    _ = _scan()

    assert f"{APP}.fixtures.users" not in sys.modules
    assert f"{APP}.seeding" not in sys.modules
    assert not hasattr(sys.modules[f"{APP}.fixtures"], "users")
    with pytest.raises(ModuleNotFoundError) as caught:
        _ = importlib.import_module(f"{APP}.fixtures.users")
    assert caught.value.name == "acme_tools"


@pytest.mark.usefixtures("application")
def test_no_stand_in_and_no_import_hook_outlive_the_scan() -> None:
    hooks = (builtins.__import__, importlib.import_module, importlib.util.find_spec)

    _ = _scan()

    assert (builtins.__import__, importlib.import_module, importlib.util.find_spec) == hooks
    assert not any(isinstance(finder, RefusalFinder) for finder in sys.meta_path)
    assert "acme_tools" not in sys.modules
    assert "acme_faker" not in sys.modules


def test_a_failing_scan_still_leaves_nothing_behind(application: ScratchModules) -> None:
    application.write(
        {
            f"{APP}.zz_mailer": (
                "from xtr_dependency_injection import as_service\nimport acme_faker\n\n\n"
                "@as_service\nclass Mailer:\n    pass\n"
            )
        }
    )
    hooks = (builtins.__import__, importlib.import_module, importlib.util.find_spec)

    with pytest.raises(SetAsideModuleUsedError):
        _ = _scan()

    assert (builtins.__import__, importlib.import_module, importlib.util.find_spec) == hooks
    assert f"{APP}.fixtures.users" not in sys.modules
    assert f"{APP}.zz_mailer" not in sys.modules


@pytest.mark.usefixtures("application")
def test_a_second_scan_sets_aside_the_same_modules() -> None:
    first, _ = _scan()
    second, _ = _scan()

    assert _set_aside(second) == _set_aside(first)


# --- packages and the import system ----------------------------------------------------

FAKE_PACKAGE = "import acme_faker\n\nfake = acme_faker.Faker()\n"


@pytest.mark.parametrize(
    "importing",
    [
        f"from {APP}.fixtures import base\n",
        f"import {APP}.fixtures.base as base\n",
        f"from {APP}.fixtures import base as b\nimport {APP}.fixtures.base\n",
    ],
    ids=["from-package-import-module", "import-as", "import-twice"],
)
def test_a_set_aside_sibling_is_served_however_it_is_imported(
    application: ScratchModules, importing: str
) -> None:
    application.write(
        {
            f"{APP}.fixtures.base": "import acme_faker\n\n\nclass Base:\n    pass\n",
            f"{APP}.fixtures.orders": importing,
        }
    )

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.fixtures.orders"] == (
        ("acme_faker",),
        f"{APP}.fixtures.base",
    )


def test_a_set_aside_module_is_reached_by_its_dotted_name_after_importing_it(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.fx_a": "import acme_faker\n\n\nclass Base:\n    pass\n",
            f"{APP}.fx_b": (
                f"import os\nimport {APP}.fx_a\n\n\nclass B({APP}.fx_a.Base):\n    pass\n"
            ),
        }
    )

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.fx_b"] == (("acme_faker",), f"{APP}.fx_a")
    assert not hasattr(sys.modules[APP], "fx_a")


@pytest.mark.parametrize(
    "child",
    ["import os\n\n\nclass Users:\n    pass\n", f"from {APP}.seeds import fake\n"],
    ids=["importing-anything", "importing-from-its-package"],
)
def test_a_child_of_a_set_aside_package_with_imports_is_set_aside_through_it(
    application: ScratchModules, child: str
) -> None:
    application.write({f"{APP}.seeds.__init__": FAKE_PACKAGE, f"{APP}.seeds.users": child})

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.seeds.users"] == (("acme_faker",), f"{APP}.seeds")
    assert f"{APP}.seeds.users" not in sys.modules


def test_a_child_of_a_set_aside_package_imported_first_by_another_module_is_not_kept(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.aaa_seed": f"import acme_faker\nimport {APP}.seeds.users\n",
            f"{APP}.seeds.__init__": FAKE_PACKAGE,
            f"{APP}.seeds.users": (
                f"from {APP}.seeds import fake\n\n\nclass UserSeed:\n    name = fake.name()\n"
            ),
        }
    )

    scanner, result = _scan()

    assert _set_aside(scanner)[f"{APP}.seeds.users"] == (("acme_faker",), f"{APP}.seeds")
    assert f"{APP}.seeds.users:UserSeed" not in _services(result)
    assert f"{APP}.seeds.users" not in scanner.modules


RE_EXPORTING = "from .users import UserFixtures\n"


def test_a_package_re_exporting_a_set_aside_module_is_set_aside_through_it(
    application: ScratchModules,
) -> None:
    application.write({f"{APP}.fixtures.__init__": RE_EXPORTING})

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.fixtures"] == (
        ("acme_faker", "acme_tools"),
        f"{APP}.fixtures.users",
    )
    assert f"{APP}.fixtures" not in sys.modules
    assert f"{APP}.fixtures" not in scanner.modules


@pytest.mark.parametrize("seed", ["aa_seed", "zz_seed"])
def test_a_module_importing_a_re_exporting_package_is_refused_whatever_its_order(
    application: ScratchModules, seed: str
) -> None:
    application.write(
        {
            f"{APP}.fixtures.__init__": RE_EXPORTING,
            f"{APP}.{seed}": f"from {APP}.fixtures import UserFixtures\n",
            f"{APP}.zz_report": (
                "from xtr_dependency_injection import as_service\n"
                f"from {APP}.fixtures import UserFixtures\n\n\n"
                "@as_service\nclass Report:\n    fixtures = UserFixtures\n"
            ),
        }
    )

    with pytest.raises(SetAsideModuleUsedError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.zz_report"
    assert caught.value.through == f"{APP}.fixtures"


def test_a_module_probing_behind_a_re_exporting_package_learns_the_truth(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.fixtures.__init__": RE_EXPORTING,
            f"{APP}.fixtures.users": FIXTURES + f"\nimport {APP}.probing\n",
            f"{APP}.probing": (
                "try:\n    import acme_faker\nexcept ImportError:\n    acme_faker = None\n\n\n"
                "class Slugger:\n    FAKER = acme_faker\n"
            ),
        }
    )

    _, result = _scan()

    assert f"{APP}.probing:Slugger" in _services(result)
    assert vars(sys.modules[f"{APP}.probing"])["acme_faker"] is None


def test_a_class_built_on_an_installed_package_re_exporting_a_set_aside_one_is_refused(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.a_fixtures": f"from {APP}.lib import Helper\n",
            f"{APP}.lib.__init__": "from .impl import Helper\n",
            f"{APP}.lib.impl": "import acme_faker\n\n\nclass Helper(acme_faker.Faker):\n    pass\n",
            f"{APP}.z_service": (
                "from xtr_dependency_injection import as_service\n"
                f"from {APP}.lib import Helper\n\n\n@as_service\nclass Z(Helper):\n    pass\n"
            ),
        }
    )

    with pytest.raises(SetAsideModuleUsedError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.z_service"


def test_each_module_of_a_failing_chain_runs_once_more_only(application: ScratchModules) -> None:
    witness = "from acme_witness import RUNS\n\nRUNS.append(__name__)\n"
    application.write(
        {
            f"{APP}.c1": f"{witness}import {APP}.c2\n",
            f"{APP}.c2": f"{witness}import {APP}.c3\n",
            f"{APP}.c3": f"{witness}import {APP}.c4\n",
            f"{APP}.c4": f"{witness}import acme_faker\n",
        }
    )

    scanner, _ = _scan()

    assert {f"{APP}.c{index}" for index in range(1, 5)} <= set(_set_aside(scanner))
    runs = _runs()
    assert all(runs.count(f"{APP}.c{index}") <= 2 for index in range(1, 5))


# --- what other modules keep ------------------------------------------------------------


def test_code_naming_no_module_is_never_served(application: ScratchModules) -> None:
    application.write(
        {
            f"{APP}.bb_seed": f"import acme_faker\nimport {APP}.zz_exec\n",
            f"{APP}.zz_exec": (
                "try:\n    exec('import acme_faker', {})\n    HAS = True\n"
                "except ImportError:\n    HAS = False\n"
            ),
        }
    )

    _ = _scan()

    assert vars(sys.modules[f"{APP}.zz_exec"])["HAS"] is False


def test_a_loaded_helper_called_by_an_inspected_module_is_never_handed_a_stand_in(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.aa_util": (
                "_FAKE = None\n\n\ndef fake():\n    global _FAKE\n"
                "    if _FAKE is None:\n        import acme_faker\n"
                "        _FAKE = acme_faker.Faker()\n"
                "    return _FAKE\n"
            ),
            f"{APP}.bb_seed": (
                f"import acme_faker\nfrom {APP}.aa_util import fake\n\nNAME = fake()\n"
            ),
        }
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.bb_seed"
    assert vars(sys.modules[f"{APP}.aa_util"])["_FAKE"] is None


def test_a_helper_probing_for_an_inspected_module_learns_the_truth(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.bb_seed": (
                f"import acme_faker\nfrom {APP}.zz_util import fake\n\nNAME = fake()\n"
            ),
            f"{APP}.zz_util": (
                "_FAKE = []\n\n\ndef fake():\n    try:\n        import acme_faker\n"
                "    except ImportError:\n        return None\n"
                "    _FAKE.append(acme_faker)\n    return _FAKE[0]\n"
            ),
        }
    )

    _ = _scan()

    assert vars(sys.modules[f"{APP}.zz_util"])["_FAKE"] == []


def test_a_remembering_stand_in_runs_no_code_of_a_loaded_class(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.aa_models": (
                "class User:\n    @classmethod\n    def delete_all(cls):\n"
                "        raise RuntimeError('ran')\n"
            ),
            f"{APP}.bb_seed": (
                f"import acme_tools as f\nfrom {APP}.aa_models import User\n\n"
                "UF = f.factory_for(User)\nUF.delete_all()\n"
            ),
        }
    )

    scanner, _ = _scan()

    assert f"{APP}.bb_seed" in _set_aside(scanner)


# --- what the scan keeps track of -----------------------------------------------------


@pytest.mark.parametrize("marker", ["@exclude\n", '@when("dev")\n'])
def test_objects_left_out_of_a_set_aside_module_keep_no_later_object_from_the_scan(
    application: ScratchModules, marker: str
) -> None:
    left_out = "".join(f"{marker}def left_out_{index}():\n    pass\n\n\n" for index in range(300))
    application.write(
        {
            f"{APP}.marked": (
                "import acme_faker\nfrom xtr_dependency_injection import exclude, when\n\n\n"
                + left_out
            ),
            "acme_blib.__init__": "".join(
                f"def found_{index}():\n    pass\n\n\n" for index in range(300)
            ),
        }
    )
    scanner, _ = _scan()
    _ = gc.collect()

    found = scanner.scan(["acme_blib"], owner="blib")

    assert len(found.services) == 300


def test_what_a_set_aside_module_holds_in_a_decorated_objects_place_is_put_aside_too(
    application: ScratchModules,
) -> None:
    application.write(
        {f"{APP}.traced": "import acme_faker\n\n\n@acme_faker.traced\ndef seed():\n    pass\n"}
    )

    _, result = _scan()

    held = [s.obj for s in result.set_aside if s.name == f"{APP}.traced:seed"]
    assert len(held) == 2
    assert isinstance(held[1], StandIn)
    assert unwrapped(held[1]) is held[0]


def test_a_scanner_told_to_set_aside_does_so_with_no_package_to_explain_it(
    application: ScratchModules,
) -> None:
    del application
    scanner = Scanner(env="prod", exclude=DEFAULT_EXCLUDES, package=APP, sets_aside=True)

    _ = scanner.scan([APP], owner=None)

    assert {entry.module: entry.expected for entry in scanner.set_aside}[
        f"{APP}.fixtures.users"
    ] is False


# --- what a module first loaded during an inspection touched ---------------------------


def test_a_module_reading_from_the_inspected_one_is_set_aside_through_it(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.m_a": f"import acme_faker\n\nfake = acme_faker.Faker()\n\nimport {APP}.m_b\n",
            f"{APP}.m_b": f"from {APP}.m_a import fake\n\n\nclass B:\n    name = fake.name()\n",
        }
    )

    scanner, result = _scan()

    assert _set_aside(scanner)[f"{APP}.m_b"] == (("acme_faker",), f"{APP}.m_a")
    assert f"{APP}.m_b:B" not in _services(result)
    assert f"{APP}.m_b" not in sys.modules


@pytest.mark.parametrize(
    "child",
    [
        f"from {APP}.seeds import fake\n\n\n@as_service\nclass Plain:\n    name = fake.name()\n",
        "@as_service\nclass Plain:\n    pass\n",
    ],
    ids=["reading-its-package", "reading-nothing"],
)
def test_a_module_a_set_aside_package_imports_is_refused_through_it(
    application: ScratchModules, child: str
) -> None:
    application.write(
        {
            f"{APP}.seeds.__init__": f"{FAKE_PACKAGE}\nfrom {APP}.seeds import plain\n",
            f"{APP}.seeds.plain": f"from xtr_dependency_injection import as_service\n{child}",
        }
    )

    with pytest.raises(SetAsideModuleUsedError) as caught:
        _ = _scan()

    assert (caught.value.module, caught.value.through) == (f"{APP}.seeds.plain", f"{APP}.seeds")


@pytest.mark.parametrize(
    ("fixtures", "loader"),
    [("fixtures", "loader"), ("zz_fixtures", "aa_loader")],
    ids=["fixtures-first", "loader-first"],
)
def test_a_module_in_an_import_cycle_with_a_set_aside_one_is_refused_whatever_its_order(
    application: ScratchModules, fixtures: str, loader: str
) -> None:
    application.write(
        {
            f"{APP}.catalog.{fixtures}": (
                "import acme_faker\n\n\nclass CatalogFixtures:\n    pass\n\n\n"
                f"from {APP}.catalog import {loader}\n"
            ),
            f"{APP}.catalog.{loader}": (
                "from xtr_dependency_injection import as_service\n"
                f"from {APP}.catalog.{fixtures} import CatalogFixtures\n\n\n"
                "@as_service\nclass CatalogLoader(CatalogFixtures):\n    pass\n"
            ),
        }
    )

    with pytest.raises(SetAsideModuleUsedError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.catalog.{loader}"
    assert caught.value.missing == ("acme_faker",)


def test_a_module_set_aside_through_the_inspected_one_runs_once(
    application: ScratchModules,
) -> None:
    application.write(
        {
            "acme_registry.__init__": REGISTRY,
            f"{APP}.seeds.__init__": f"{FAKE_PACKAGE}\nfrom .commands import Seed\n",
            f"{APP}.seeds.commands": (
                "import acme_registry\n\nacme_registry.register('seed')\n\n\n"
                "class Seed:\n    pass\n"
            ),
        }
    )

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.seeds.commands"] == (("acme_faker",), f"{APP}.seeds")
    assert cast("list[str]", importlib.import_module("acme_registry").NAMES) == ["seed"]


def test_a_module_of_a_set_aside_package_imported_from_elsewhere_is_set_aside_through_it(
    application: ScratchModules,
) -> None:
    # catalog sorts before fixtures: its import reaches a module the package itself does not.
    application.write(
        {
            f"{APP}.fixtures.__init__": RE_EXPORTING,
            f"{APP}.fixtures.data": "USERS = ['ada']\n",
            f"{APP}.catalog.seed": f"from {APP}.fixtures.data import USERS\n",
        }
    )

    scanner, _ = _scan()

    set_aside = _set_aside(scanner)
    assert set_aside[f"{APP}.fixtures.data"][1] == f"{APP}.fixtures"
    assert set_aside[f"{APP}.catalog.seed"][1] == f"{APP}.fixtures"


def test_a_module_that_only_asked_for_the_missing_package_is_kept_and_runs_once(
    application: ScratchModules,
) -> None:
    application.write(
        {
            "acme_registry.__init__": REGISTRY,
            f"{APP}.aa_seed": f"import acme_faker\nfrom {APP}.zz_report import Report\n",
            f"{APP}.zz_report": (
                "import importlib.util\nimport acme_registry\n\n"
                "HAS = importlib.util.find_spec('acme_faker') is not None\n"
                "acme_registry.register('report')\n\n\nclass Report:\n    pass\n"
            ),
        }
    )

    _, result = _scan()

    assert f"{APP}.zz_report:Report" in _services(result)
    assert vars(sys.modules[f"{APP}.zz_report"])["HAS"] is False
    assert cast("list[str]", importlib.import_module("acme_registry").NAMES) == ["report"]


def test_a_module_reaching_a_set_aside_one_through_its_package_fails_as_it_would_at_runtime(
    application: ScratchModules,
) -> None:
    # Nothing imports app.fx.users truthfully: at runtime the attribute is never there either.
    application.write(
        {
            f"{APP}.fx.users": FIXTURES,
            f"{APP}.fx.orders": f"from . import users\nimport {APP}.zb\n",
            f"{APP}.zb": (
                f"import {APP}.fx\n\n\nclass Svc:\n    dep = {APP}.fx.users.UserFixtures\n"
            ),
        }
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert isinstance(caught.value.__cause__, AttributeError)


def test_a_mistake_in_a_fallback_for_a_missing_package_stays_fatal(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.fallback": (
                "try:\n    import acme_ujson as json\n"
                f"except ImportError:\n    from {APP}.services import Usr\n"
            )
        }
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.fallback"


def test_a_helper_the_failed_import_loaded_is_never_handed_a_stand_in(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.fx2": f"import {APP}.zmaker\n\nF = {APP}.zmaker.make()\n",
            f"{APP}.zmaker": (
                "CACHE = []\n\n\ndef make():\n    import acme_faker\n"
                "    CACHE.append(acme_faker)\n    return acme_faker\n"
            ),
        }
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.fx2"
    assert vars(sys.modules[f"{APP}.zmaker"])["CACHE"] == []


def test_a_bare_package_holds_what_its_body_defined_before_it_failed(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.seeds.__init__": "LOCALE = 'en_US'\n\nfrom .people import People\n",
            f"{APP}.seeds.people": (
                "import acme_faker\nfrom . import LOCALE\n\n\nclass People:\n    locale = LOCALE\n"
            ),
        }
    )

    scanner, _ = _scan()

    set_aside = _set_aside(scanner)
    assert set_aside[f"{APP}.seeds.people"] == (("acme_faker",), None)
    assert set_aside[f"{APP}.seeds"] == (("acme_faker",), f"{APP}.seeds.people")


def test_code_an_inspected_module_runs_with_no_module_name_is_served_as_its_own(
    application: ScratchModules,
) -> None:
    # Code run with a bare namespace takes the builtins of the module running it.
    application.write({f"{APP}.execs": "import acme_faker\n\nexec('import acme_faker', {})\n"})

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.execs"] == (("acme_faker",), None)


# --- what the failed import before an inspection loaded --------------------------------


def test_the_other_half_of_a_cycle_imported_before_the_failing_line_stays_as_that_import_left_it(
    application: ScratchModules,
) -> None:
    # Loaded by the truthful import that failed after it, it holds that module half-run, as it
    # would at runtime: nothing tells the scan it imported it. Scanned first, it is refused:
    # see the test below.
    application.write(
        {
            f"{APP}.aa_fx": f"import {APP}.zz_helper\nimport acme_faker\n\n\nclass F:\n    pass\n",
            f"{APP}.zz_helper": (
                "from xtr_dependency_injection import as_service\n"
                f"from {APP} import aa_fx\n\n\n@as_service\nclass Helper:\n    pass\n"
            ),
        }
    )

    scanner, result = _scan()

    assert f"{APP}.zz_helper:Helper" in _services(result)
    assert f"{APP}.aa_fx" in _set_aside(scanner)
    half_run = cast("object", vars(sys.modules[f"{APP}.zz_helper"])["aa_fx"])
    assert "F" not in vars(half_run)


def test_the_other_half_of_a_cycle_scanned_before_the_failing_module_is_refused(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.zz_fx": f"import {APP}.aa_helper\nimport acme_faker\n\n\nclass F:\n    pass\n",
            f"{APP}.aa_helper": (
                "from xtr_dependency_injection import as_service\n"
                f"from {APP} import zz_fx\n\n\n@as_service\nclass Helper:\n    pass\n"
            ),
        }
    )

    with pytest.raises(SetAsideModuleUsedError) as caught:
        _ = _scan()

    assert (caught.value.module, caught.value.through) == (f"{APP}.aa_helper", f"{APP}.zz_fx")


def test_a_healthy_module_its_package_loads_before_a_fixture_runs_once(
    application: ScratchModules,
) -> None:
    application.write(
        {
            "acme_registry.__init__": REGISTRY,
            f"{APP}.fixtures.__init__": "from .load import load\nfrom .users import UserFixtures\n",
            f"{APP}.fixtures.load": (
                "import acme_registry\n\nacme_registry.register('load')\n\n\n"
                "def load():\n    pass\n"
            ),
        }
    )

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.fixtures.load"][1] == f"{APP}.fixtures"
    assert cast("list[str]", importlib.import_module("acme_registry").NAMES) == ["load"]


def test_a_module_only_asking_whether_a_set_aside_module_exists_is_kept(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.zz_seed": f"import {APP}.fixtures.users\nimport {APP}.zz_zreport\n",
            f"{APP}.zz_zreport": (
                "import importlib.util\n\n"
                f"HAS = importlib.util.find_spec('{APP}.fixtures.users') is not None\n\n\n"
                "class Report:\n    pass\n"
            ),
        }
    )

    scanner, result = _scan()

    assert f"{APP}.zz_zreport" not in _set_aside(scanner)
    assert f"{APP}.zz_zreport:Report" in _services(result)


def test_a_package_whose_modules_import_what_it_re_exports_is_set_aside(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.fixtures.__init__": (
                "from .users import UserFixtures\nfrom .orders import OrderFixtures\n"
            ),
            f"{APP}.fixtures.orders": (
                "from acme_tools.fixtures import Fixture\n"
                f"from {APP}.fixtures import UserFixtures\n\n\n"
                "class OrderFixtures(Fixture):\n    after = UserFixtures\n"
            ),
        }
    )

    scanner, _ = _scan()

    set_aside = _set_aside(scanner)
    assert {f"{APP}.fixtures", f"{APP}.fixtures.orders", f"{APP}.fixtures.users"} <= set(set_aside)


def test_a_set_aside_module_is_reached_by_its_dotted_name_after_an_optional_import(
    application: ScratchModules,
) -> None:
    # An inspected module is served a stand-in for a package it only tries: it is said to need it.
    application.write(
        {
            f"{APP}.zz_seeder": (
                f"import {APP}.fixtures.users\n"
                "try:\n    import acme_orjson\nexcept ImportError:\n    acme_orjson = None\n\n\n"
                f"class Seeder:\n    fixtures = [{APP}.fixtures.users.UserFixtures]\n"
            )
        }
    )

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.zz_seeder"] == (
        ("acme_faker", "acme_orjson", "acme_tools"),
        None,
    )


def test_a_set_aside_package_keeps_the_modules_its_own_body_imported(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.seeds.__init__": "from .people import People\n",
            f"{APP}.seeds.people": "import acme_faker\n\n\nclass People:\n    pass\n",
            f"{APP}.zz_use": f"import {APP}.seeds\n\nP = {APP}.seeds.people.People\n",
        }
    )

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.zz_use"][1] == f"{APP}.seeds"


def test_a_module_a_failed_package_loaded_truthfully_stays_and_runs_once(
    application: ScratchModules,
) -> None:
    # As a failed import leaves it: an optional import of the package finds it, not running it.
    application.write(
        {
            "acme_registry.__init__": REGISTRY,
            f"{APP}.seeds.__init__": "from .plain import Plain\nimport acme_faker\n",
            f"{APP}.seeds.plain": (
                "import acme_registry\n\nacme_registry.register('plain')\n\n\n"
                "class Plain:\n    pass\n"
            ),
            f"{APP}.zz_opt": f"try:\n    import {APP}.seeds\nexcept ImportError:\n    pass\n",
        }
    )

    scanner, _ = _scan()

    (plain,) = [entry for entry in scanner.set_aside if entry.module == f"{APP}.seeds.plain"]
    assert (plain.through, plain.defines) == (f"{APP}.seeds", (f"{APP}.seeds.plain:Plain",))
    assert cast("list[str]", importlib.import_module("acme_registry").NAMES) == ["plain"]
    assert f"{APP}.seeds" not in sys.modules


def test_an_import_error_naming_the_missing_package_is_read_through(
    application: ScratchModules,
) -> None:
    application.write(
        {
            "acme_extra2.__init__": (
                "try:\n    import acme_faker\nexcept ModuleNotFoundError as error:\n"
                "    raise ImportError('install acme_extra2[fake]', name='acme_faker') from error\n"
            ),
            f"{APP}.uses_extra2": "import acme_extra2\n",
        }
    )

    scanner, _ = _scan()

    assert _set_aside(scanner)[f"{APP}.uses_extra2"] == (("acme_faker",), "acme_extra2")


def test_a_package_failing_for_a_reason_of_its_own_is_blamed_where_the_scan_meets_it(
    application: ScratchModules,
) -> None:
    # aa_opt catches the failed import, leaving zz_pkg.load loaded without its package.
    application.write(
        {
            f"{APP}.aa_opt": f"try:\n    import {APP}.zz_pkg\nexcept ImportError:\n    pass\n",
            f"{APP}.zz_pkg.__init__": "from .load import load\nfrom json import not_there\n",
            f"{APP}.zz_pkg.load": "def load():\n    pass\n",
        }
    )

    with pytest.raises(ResourceImportError) as caught:
        # Scanned without the check of what is left: the failed import leaves its module, as ever.
        _ = _scanner().scan([APP], owner=None)

    assert caught.value.module == f"{APP}.zz_pkg"
    assert f"{APP}.zz_pkg.load" in sys.modules
    assert f"{APP}.zz_pkg" not in sys.modules


@pytest.mark.parametrize(("package", "catcher"), [("aa_pkg", "zz_opt"), ("zz_pkg", "aa_opt")])
def test_a_package_failing_with_any_error_of_its_own_is_blamed_whatever_the_order(
    application: ScratchModules, package: str, catcher: str
) -> None:
    application.write(
        {
            f"{APP}.{catcher}": f"try:\n    import {APP}.{package}\nexcept Exception:\n    pass\n",
            f"{APP}.{package}.__init__": "from .load import load\nraise ValueError('boom')\n",
            f"{APP}.{package}.load": "def load():\n    pass\n",
        }
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = _scanner().scan([APP], owner=None)

    assert caught.value.module == f"{APP}.{package}"
    assert isinstance(caught.value.__cause__, ValueError)


def test_a_module_named_as_a_resource_inside_a_set_aside_package_runs_once(
    application: ScratchModules,
) -> None:
    # Its package's own code imports it: set aside then, it is not run again when named.
    application.write(
        {
            "acme_registry.__init__": REGISTRY,
            f"{APP}.seeds.__init__": "import acme_faker\nfrom . import people\n",
            f"{APP}.seeds.people": "import acme_registry\n\nacme_registry.register('people')\n",
        }
    )

    scanner = _scanner()
    _ = scanner.scan([f"{APP}.seeds", f"{APP}.seeds.people"], owner=None)

    assert _set_aside(scanner)[f"{APP}.seeds.people"][1] == f"{APP}.seeds"
    assert cast("list[str]", importlib.import_module("acme_registry").NAMES) == ["people"]


def test_a_module_a_set_aside_one_put_among_the_loaded_modules_is_set_aside_as_it_is(
    application: ScratchModules,
) -> None:
    application.write(
        {
            f"{APP}.aa_fx": (
                "import sys\nimport types\nimport acme_faker\n\n"
                f"made = types.ModuleType('{APP}.aa_fx_made')\nmade.VALUE = 1\n"
                f"sys.modules['{APP}.aa_fx_made'] = made\n"
            ),
            f"{APP}.bb_user": f"import acme_faker\nfrom {APP}.aa_fx_made import VALUE\n",
        }
    )

    scanner, _ = _scan()

    assert {f"{APP}.aa_fx", f"{APP}.bb_user"} <= set(_set_aside(scanner))
