from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from xtr_dependency_injection.discovery import discover_bundles
from xtr_dependency_injection.exception import DuplicateBundleError

if TYPE_CHECKING:
    from tests.support.fake_dist import FakeDistributions

BUNDLE = """
from xtr_dependency_injection.bundle import Bundle, as_bundle


@as_bundle("{name}")
class {cls}(Bundle):
    pass
"""


def _source(name: str, cls: str) -> str:
    return BUNDLE.format(name=name, cls=cls)


def test_an_installed_bundle_is_discovered(fake_dist: FakeDistributions) -> None:
    fake_dist.install(
        "acme-alpha",
        {"alpha": "acme_alpha:AlphaBundle"},
        {"acme_alpha": _source("alpha", "AlphaBundle")},
    )

    (found,) = discover_bundles()

    assert (found.name, found.value, found.distribution, found.reason) == (
        "alpha",
        "acme_alpha:AlphaBundle",
        "acme-alpha",
        None,
    )
    assert found.bundle is not None
    assert found.bundle.__name__ == "AlphaBundle"


def test_bundles_are_sorted_by_name(fake_dist: FakeDistributions) -> None:
    fake_dist.install("acme-zeta", {"zeta": "acme_zeta:Z"}, {"acme_zeta": _source("zeta", "Z")})
    fake_dist.install("acme-beta", {"beta": "acme_beta:B"}, {"acme_beta": _source("beta", "B")})

    assert [found.name for found in discover_bundles()] == ["beta", "zeta"]


def test_an_unimportable_bundle_is_skipped_with_its_reason(fake_dist: FakeDistributions) -> None:
    fake_dist.install("acme-gone", {"gone": "acme_missing_module:Gone"})

    (found,) = discover_bundles()

    assert found.bundle is None
    assert found.reason is not None
    assert found.reason.startswith("cannot import acme_missing_module:Gone")


def test_an_object_that_is_not_a_bundle_is_skipped(fake_dist: FakeDistributions) -> None:
    fake_dist.install("acme-odd", {"odd": "acme_odd:Odd"}, {"acme_odd": "class Odd:\n    pass\n"})

    (found,) = discover_bundles()

    assert found.reason == "acme_odd:Odd is not a Bundle subclass"


def test_an_undecorated_bundle_is_skipped(fake_dist: FakeDistributions) -> None:
    source = (
        "from xtr_dependency_injection.bundle import Bundle\n\nclass Plain(Bundle):\n    pass\n"
    )
    fake_dist.install("acme-plain", {"plain": "acme_plain:Plain"}, {"acme_plain": source})

    (found,) = discover_bundles()

    assert found.reason == "acme_plain:Plain is not decorated with @as_bundle"


def test_a_bundledeclare_bundle_another_name_is_skipped(fake_dist: FakeDistributions) -> None:
    fake_dist.install(
        "acme-liar", {"liar": "acme_liar:Liar"}, {"acme_liar": _source("honest", "Liar")}
    )

    (found,) = discover_bundles()

    assert found.reason == "acme_liar:Liar declares the name 'honest', not 'liar'"


def test_one_bundle_advertised_twice_counts_once(fake_dist: FakeDistributions) -> None:
    fake_dist.install("acme-one", {"one": "acme_one:One"}, {"acme_one": _source("one", "One")})
    fake_dist.install("acme-one-again", {"one": "acme_one:One"})

    assert [found.name for found in discover_bundles()] == ["one"]


def test_one_name_pointing_at_two_classes_is_refused(fake_dist: FakeDistributions) -> None:
    fake_dist.install("acme-one", {"one": "acme_one:One"}, {"acme_one": _source("one", "One")})
    fake_dist.install("acme-two", {"one": "acme_two:Two"}, {"acme_two": _source("one", "Two")})

    with pytest.raises(DuplicateBundleError) as caught:
        _ = discover_bundles()

    assert (caught.value.first, caught.value.second) == ("acme_one:One", "acme_two:Two")


def test_nothing_installed_discovers_nothing() -> None:
    assert discover_bundles() == ()
