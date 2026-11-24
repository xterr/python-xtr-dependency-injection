from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
import threading
from typing import TYPE_CHECKING, override

import pytest

from xtr_dependency_injection.scan._refusal import RefusalFinder, SetAsideRefused, holder_of

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from types import ModuleType

    from tests.support.modules import ScratchModules


@pytest.fixture
def refusing(scratch_modules: ScratchModules) -> Iterator[set[str]]:
    scratch_modules.write(
        {
            "acme_app.seed": "RAN = True\n",
            "acme_app.seeds.users": "RAN = True\n",
            "acme_app.asking": "from acme_app import seed\n",
        }
    )
    set_aside = {"acme_app.seed", "acme_app.seeds"}
    finder = RefusalFinder(set_aside, lambda through: "acme_faker")
    finder.install()
    try:
        yield set_aside
    finally:
        finder.remove()


@pytest.mark.usefixtures("refusing")
def test_a_set_aside_module_is_refused_and_not_loaded() -> None:
    with pytest.raises(SetAsideRefused) as caught:
        _ = importlib.import_module("acme_app.seed")

    assert (caught.value.module, caught.value.through) == ("acme_app.seed", "acme_app.seed")
    assert "acme_app.seed" not in sys.modules


@pytest.mark.usefixtures("refusing")
def test_a_refusal_reads_as_the_failure_of_a_truthful_import() -> None:
    with pytest.raises(ModuleNotFoundError) as caught:
        _ = importlib.import_module("acme_app.seed")

    assert caught.value.name == "acme_faker"
    assert str(caught.value) == "No module named 'acme_faker'"


@pytest.mark.usefixtures("refusing")
def test_a_module_under_a_set_aside_package_is_refused_through_it() -> None:
    with pytest.raises(ImportError) as caught:
        _ = importlib.import_module("acme_app.seeds.users")

    assert isinstance(caught.value, SetAsideRefused)
    assert caught.value.through == "acme_app.seeds"


@pytest.mark.usefixtures("refusing")
def test_taking_a_set_aside_module_from_its_package_is_refused_not_taken_for_a_missing_name() -> (
    None
):
    with pytest.raises(SetAsideRefused):
        _ = importlib.import_module("acme_app.asking")


@pytest.mark.usefixtures("refusing")
def test_asking_whether_a_set_aside_module_exists_is_answered_as_ever() -> None:
    found = importlib.util.find_spec("acme_app.seed")

    assert found is not None
    assert found.origin is not None
    assert found.origin.endswith("seed.py")


_RECORD = importlib.machinery.ModuleSpec("acme_cached", loader=None)


class _Caching(importlib.abc.MetaPathFinder):
    """Hands out the same record each time it is asked."""

    @override
    def find_spec(
        self, fullname: str, path: Sequence[str] | None, target: ModuleType | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        del path, target
        return _RECORD if fullname == "acme_cached" else None


def test_the_record_another_finder_found_is_not_changed() -> None:
    caching = _Caching()
    sys.meta_path.append(caching)
    try:
        refused = RefusalFinder({"acme_cached"}, lambda through: "acme_faker").find_spec(
            "acme_cached", None
        )
    finally:
        sys.meta_path.remove(caching)

    assert refused is not None
    assert refused is not _RECORD
    assert _RECORD.loader is None


def test_a_name_set_aside_later_is_refused_too(refusing: set[str]) -> None:
    _ = importlib.import_module("acme_app")
    refusing.add("acme_app.asking")

    with pytest.raises(SetAsideRefused):
        _ = importlib.import_module("acme_app.asking")


def test_another_thread_is_refused_nothing(refusing: set[str]) -> None:
    del refusing
    loaded: list[object] = []
    thread = threading.Thread(
        target=lambda: loaded.append(importlib.import_module("acme_app.seed"))
    )

    thread.start()
    thread.join()

    assert len(loaded) == 1


def test_a_module_is_held_by_the_package_it_is_or_lies_in() -> None:
    packages = ["acme_app.seeds"]

    assert holder_of("acme_app.seeds", packages) == "acme_app.seeds"
    assert holder_of("acme_app.seeds.users", packages) == "acme_app.seeds"
    assert holder_of("acme_app.seeds_more", packages) is None


def test_a_module_held_by_two_set_aside_packages_is_held_by_the_nearest() -> None:
    # A module set aside under a loaded package, whose package was set aside later.
    packages = {"acme_app.seeds.users": None, "acme_app.seeds": None}

    assert holder_of("acme_app.seeds.users.admins", packages) == "acme_app.seeds.users"
    assert holder_of("acme_app.seeds.orders", packages) == "acme_app.seeds"
