from __future__ import annotations

from dataclasses import dataclass

import pytest

from xtr_dependency_injection.bundle import (
    Bundle,
    BundleMetadata,
    NoConfig,
    RequiredBundle,
    as_bundle,
    required_bundle,
)
from xtr_dependency_injection.exception import BundleDefinitionError


@dataclass(frozen=True)
class SampleConfig:
    level: int = 1


@dataclass(frozen=True)
class NeedsArguments:
    level: int


def test_every_argument_is_recorded() -> None:
    @as_bundle("full", config=SampleConfig, resources=["pkg.commands"])
    class FullBundle(Bundle[SampleConfig]):
        pass

    assert FullBundle.metadata() == BundleMetadata(
        name="full",
        config=SampleConfig,
        resources=("pkg.commands",),
    )


def test_no_config_type_means_no_config() -> None:
    @as_bundle("plain")
    class PlainBundle(Bundle):
        pass

    assert PlainBundle.metadata().config is NoConfig


def test_required_bundle_below_as_bundle_is_merged_into_metadata() -> None:
    @as_bundle("peer")
    class PeerBundle(Bundle):
        pass

    @as_bundle("with_required")
    @required_bundle(PeerBundle)
    class WithRequiredBundle(Bundle):
        pass

    assert WithRequiredBundle.metadata().required == (RequiredBundle(PeerBundle),)


def test_required_bundle_above_as_bundle_is_merged_into_metadata() -> None:
    @as_bundle("peer2")
    class PeerBundle(Bundle):
        pass

    @required_bundle(PeerBundle)
    @as_bundle("with_required_top")
    class WithRequiredTopBundle(Bundle):
        pass

    assert WithRequiredTopBundle.metadata().required == (RequiredBundle(PeerBundle),)


def test_required_bundle_is_repeatable_and_preserves_order() -> None:
    @as_bundle("peer_a")
    class PeerA(Bundle):
        pass

    @as_bundle("peer_b")
    class PeerB(Bundle):
        pass

    @required_bundle(PeerA)
    @required_bundle(PeerB)
    @as_bundle("multi")
    class MultiBundle(Bundle):
        pass

    # Decoration order top-down: PeerB was applied first (closer to the class),
    # then PeerA, so the list ends up (PeerB, PeerA).
    targets = [declaration.target for declaration in MultiBundle.metadata().required]
    assert targets == [PeerB, PeerA]


def test_a_string_required_target_records_the_string() -> None:
    @required_bundle("some.module:LazyBundle", ignore_on_invalid=True)
    @as_bundle("with_lazy")
    class WithLazyBundle(Bundle):
        pass

    assert WithLazyBundle.metadata().required == (
        RequiredBundle("some.module:LazyBundle", ignore_on_invalid=True),
    )


def test_a_malformed_string_target_is_refused() -> None:
    with pytest.raises(BundleDefinitionError, match="module:Class"):
        _ = required_bundle("no_colon_here")


@pytest.mark.parametrize("name", ["Upper", "1digit", "with-dash", "", "_under"])
def test_an_invalid_name_is_refused(name: str) -> None:
    with pytest.raises(BundleDefinitionError, match="lowercase letters"):
        _ = as_bundle(name)


def test_the_kernel_name_is_reserved() -> None:
    with pytest.raises(BundleDefinitionError, match="reserved"):
        _ = as_bundle("kernel")


def test_a_config_type_needing_arguments_is_refused() -> None:
    with pytest.raises(BundleDefinitionError, match="config type cannot be built"):
        _ = as_bundle("strict", config=NeedsArguments)


def test_a_class_that_is_not_a_bundle_is_refused() -> None:
    class NotABundle:
        pass

    with pytest.raises(BundleDefinitionError, match="is not a Bundle subclass"):
        # Deliberately the wrong type: the check exists for untyped callers.
        as_bundle("plain")(NotABundle)  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]


def test_a_bundle_requiring_constructor_arguments_is_refused() -> None:
    class Needy(Bundle):
        def __init__(self, dependency: object) -> None:
            self.dependency: object = dependency

    with pytest.raises(BundleDefinitionError, match="requires constructor arguments"):
        _ = as_bundle("needy")(Needy)


@pytest.mark.parametrize("resource", ["", 0, None])
def test_a_resource_that_is_not_a_non_empty_string_is_refused(resource: object) -> None:
    with pytest.raises(BundleDefinitionError, match="must be a non-empty string"):
        _ = as_bundle("bad_resources", resources=[resource])  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]


def test_a_bundle_requiring_itself_by_class_reference_is_refused() -> None:
    class Placeholder(Bundle):
        pass

    setattr(Placeholder, "__xtr_required_bundles__", (RequiredBundle(Placeholder),))  # noqa: B010 — the attribute is added by the decorator we bypass here.

    with pytest.raises(BundleDefinitionError, match="cannot list itself"):
        _ = as_bundle("self_ref")(Placeholder)


def test_a_bundle_requiring_itself_by_string_target_is_refused() -> None:
    class Twin(Bundle):
        pass

    self_target = f"{Twin.__module__}:{Twin.__qualname__}"
    setattr(Twin, "__xtr_required_bundles__", (RequiredBundle(self_target),))  # noqa: B010 — the attribute is added by the decorator we bypass here.

    with pytest.raises(BundleDefinitionError, match="cannot list itself"):
        _ = as_bundle("self_str")(Twin)
