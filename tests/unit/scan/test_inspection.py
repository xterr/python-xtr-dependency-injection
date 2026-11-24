"""How a module is inspected: its code run in a namespace of its own, its imports served."""

from __future__ import annotations

import builtins
import dataclasses
import importlib
import importlib.util
import sys
from typing import TYPE_CHECKING, cast

import pytest

from xtr_dependency_injection.exception import ResourceImportError
from xtr_dependency_injection.scan import DEFAULT_EXCLUDES
from xtr_dependency_injection.scan._inspection import _code_of
from xtr_dependency_injection.scan._stand_ins import StandIn
from xtr_dependency_injection.scan.scanner import Scanner

if TYPE_CHECKING:
    import enum
    from collections.abc import Callable
    from types import FunctionType

    from _typeshed import DataclassInstance

    from tests.support.modules import ScratchModules
    from xtr_dependency_injection.scan.scanner import ScanResult

APP = "acme_app"

TYPED = """
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import ClassVar, Generic, TypeVar

import acme_faker

T = TypeVar("T")
fake = acme_faker.Faker()


@dataclass
class Row:
    name: str
    tags: list[str] = field(default_factory=list)
    kind: ClassVar[str] = "row"


class Kind(enum.Enum):
    USER = "user"
    ORDER = "order"


class Box(Generic[T]):
    def __init__(self, held: T) -> None:
        self.held = held


class Rows[R]:
    first: R | None = None


INT_BOX = Box[int](3)
SELF = __import__("sys").modules[__name__]
"""


def _scan() -> tuple[Scanner, ScanResult]:
    scanner = Scanner(
        env="prod", exclude=DEFAULT_EXCLUDES, package=APP, inactive_packages=("acme_tools",)
    )
    return scanner, scanner.scan([APP], owner=None)


def _set_aside_object(result: ScanResult, name: str) -> object:
    (found,) = [scanned.obj for scanned in result.set_aside if scanned.name == name]
    return found


def test_a_dataclass_an_enum_and_generics_of_an_inspected_module_are_what_they_would_be(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write({f"{APP}.typed": TYPED})

    scanner, result = _scan()

    (entry,) = scanner.set_aside
    assert entry.defines == tuple(f"{APP}.typed:{name}" for name in ("Row", "Kind", "Box", "Rows"))
    row = cast("type[DataclassInstance]", _set_aside_object(result, f"{APP}.typed:Row"))
    assert [field.name for field in dataclasses.fields(row)] == ["name", "tags"]
    assert repr(cast("Callable[[str], object]", row)("ada")) == "Row(name='ada', tags=[])"
    kind = cast("type[enum.Enum]", _set_aside_object(result, f"{APP}.typed:Kind"))
    assert [member.name for member in kind] == ["USER", "ORDER"]
    assert f"{APP}.typed" not in sys.modules


def test_an_inspected_module_finds_itself_among_the_loaded_modules_for_its_own_body_only(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write({f"{APP}.typed": TYPED})

    _, result = _scan()

    box = cast("type", _set_aside_object(result, f"{APP}.typed:Box"))
    namespace = cast("FunctionType", vars(box)["__init__"]).__globals__
    # What it read off sys.modules by its own name, while its body ran, was itself.
    assert vars(cast("object", namespace["SELF"])) is namespace
    assert f"{APP}.typed" not in sys.modules


def test_a_function_of_a_set_aside_module_imports_truthfully_once_the_scan_is_over(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write(
        {
            f"{APP}.lazy": (
                "import acme_faker\n\n\ndef during():\n    import acme_faker.providers as p\n"
                "    return p\n\n\nDURING = during()\n"
            )
        }
    )

    _, result = _scan()

    during = cast("FunctionType", _set_aside_object(result, f"{APP}.lazy:during"))
    assert isinstance(during.__globals__["DURING"], StandIn)
    with pytest.raises(ModuleNotFoundError):
        _ = cast("object", during())


def test_a_failure_an_inspected_module_swallows_is_fatal_all_the_same(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write(
        {
            f"{APP}.outer": (
                f"import acme_faker\ntry:\n    import {APP}.zz_inner\nexcept Exception:\n    pass\n"
            ),
            f"{APP}.zz_inner": "import json\nimport acme_faker\n\njson.dumps(acme_faker.data)\n",
        }
    )

    with pytest.raises(ResourceImportError) as caught:
        _ = _scan()

    assert caught.value.module == f"{APP}.zz_inner"


def test_a_module_with_no_code_to_run_again_is_fatal() -> None:
    record = importlib.util.find_spec("_json")

    with pytest.raises(ResourceImportError) as caught:
        _ = _code_of("_json", record)

    assert "has no code to run again" in caught.value.__notes__[0]


def test_an_inspected_module_sees_the_builtins_as_they_are_now(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write(
        {
            f"{APP}.flagged": (
                "import builtins\n\nbuiltins.ACME_FLAG = 1\nimport acme_faker\n\n"
                "VALUE = ACME_FLAG\n"
            )
        }
    )
    try:
        scanner, _ = _scan()
    finally:
        if hasattr(builtins, "ACME_FLAG"):
            delattr(builtins, "ACME_FLAG")

    assert [entry.module for entry in scanner.set_aside] == [f"{APP}.flagged"]


def test_the_namespace_of_a_set_aside_module_is_refused_to_this_package_outside_the_scan(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write({f"{APP}.typed": TYPED})
    _, result = _scan()
    box = cast("type", _set_aside_object(result, f"{APP}.typed:Box"))
    namespace = cast("object", cast("FunctionType", vars(box)["__init__"]).__globals__["SELF"])
    # As a boot hook of a bundle would read it: code of this package, but not the scan's.
    reading: dict[str, object] = {
        "__name__": "xtr_dependency_injection.kernel.hook",
        "held": namespace,
    }

    with pytest.raises(ModuleNotFoundError):
        exec("held.fake", reading)  # noqa: S102 — code run under a module name of this package


def test_a_loaded_package_reached_through_a_set_aside_module_answers_its_own_dunders(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write(
        {
            f"{APP}.aa_fx": "import acme_faker\n",
            f"{APP}.bb_user": (
                f"import {APP}.aa_fx\n\nRECORD = {APP}.__spec__.name\nPACKAGE = {APP}.__package__\n"
            ),
        }
    )

    scanner, result = _scan()

    del result
    (user,) = [entry for entry in scanner.set_aside if entry.module == f"{APP}.bb_user"]
    assert user.through == f"{APP}.aa_fx"


def test_the_namespace_of_a_set_aside_module_refuses_its_names_to_other_code(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write({f"{APP}.typed": TYPED})

    _, result = _scan()

    box = cast("type", _set_aside_object(result, f"{APP}.typed:Box"))
    # What its body read off sys.modules by its own name: the namespace itself.
    namespace = cast("object", cast("FunctionType", vars(box)["__init__"]).__globals__["SELF"])
    own, dunder = "fake", "__name__"
    with pytest.raises(ModuleNotFoundError) as caught:
        _ = cast("object", getattr(namespace, own))
    assert caught.value.name == "acme_faker"
    assert cast("str", getattr(namespace, dunder)) == f"{APP}.typed"
