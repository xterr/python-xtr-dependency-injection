"""``installed_bundles`` reads what distributions advertise, keeping only usable bundles."""

from __future__ import annotations

import importlib
from importlib.metadata import EntryPoint
from typing import TYPE_CHECKING

from tests.support.bundles import ChorusBundle, EchoBundle
from xtr_dependency_injection.bundle import BUNDLES_ENTRY_POINT_GROUP, installed_bundles

if TYPE_CHECKING:
    import pytest

# The package re-exports the function under the module's own name, so the
# module is fetched from the import system rather than by attribute.
_MODULE = importlib.import_module("xtr_dependency_injection.bundle.installed_bundles")


def _advertise(monkeypatch: pytest.MonkeyPatch, **targets: str) -> None:
    """Make ``targets`` — entry point name to ``module:Class`` — the only ones installed."""
    advertised = tuple(
        EntryPoint(name, value, BUNDLES_ENTRY_POINT_GROUP) for name, value in targets.items()
    )

    def entry_points(*, group: str) -> tuple[EntryPoint, ...]:
        return advertised if group == BUNDLES_ENTRY_POINT_GROUP else ()

    monkeypatch.setattr(_MODULE, "entry_points", entry_points)


def test_it_returns_every_advertised_bundle_ordered_by_entry_point_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _advertise(
        monkeypatch,
        echo="tests.support.bundles:EchoBundle",
        chorus="tests.support.bundles:ChorusBundle",
    )

    assert installed_bundles() == (ChorusBundle, EchoBundle)


def test_it_skips_a_target_that_cannot_be_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    _advertise(
        monkeypatch,
        absent="xtr_no_such_module_anywhere.bundle:AbsentBundle",
        echo="tests.support.bundles:EchoBundle",
    )

    assert installed_bundles() == (EchoBundle,)


def test_it_skips_a_target_that_is_not_a_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    _advertise(monkeypatch, plugin="tests.support.bundles:Plugin")

    assert installed_bundles() == ()


def test_it_returns_a_bundle_advertised_twice_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _advertise(
        monkeypatch,
        echo="tests.support.bundles:EchoBundle",
        echo_again="tests.support.bundles:EchoBundle",
    )

    assert installed_bundles() == (EchoBundle,)
