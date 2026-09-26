"""Kernel-level tests for ``@as_tagged_item``: priority order, before/after, index as key."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.fixtures.app_tagged_aliases import Pipeline
from tests.fixtures.app_tagged_before import A as BeforeA
from tests.fixtures.app_tagged_before import B as BeforeB
from tests.fixtures.app_tagged_items import HighPriority, LowPriority
from xtr_dependency_injection.exception.service_order_error import ServiceOrderError
from xtr_dependency_injection.kernel import Kernel

if TYPE_CHECKING:
    from xtr_dependency_injection.kernel.compiled_kernel import CompiledKernel

pytestmark = pytest.mark.anyio


def _emission_types(compiled: CompiledKernel) -> list[type]:
    return [d.key[0] for d in compiled.report.definitions]


def test_a_higher_priority_tagged_item_is_emitted_first() -> None:
    compiled = Kernel("tests.fixtures.app_tagged_items", bundles={}).build()

    types = _emission_types(compiled)

    assert types.index(HighPriority) < types.index(LowPriority)


def test_a_tagged_items_index_is_its_qualifier() -> None:
    compiled = Kernel("tests.fixtures.app_tagged_items", bundles={}).build()

    keys = {d.key for d in compiled.report.definitions}

    assert (HighPriority, "high") in keys
    assert (LowPriority, "low") in keys


def test_an_unprioritised_tagged_item_is_placed_by_before() -> None:
    compiled = Kernel("tests.fixtures.app_tagged_before", bundles={}).build()

    types = _emission_types(compiled)

    assert types.index(BeforeA) < types.index(BeforeB)


def test_an_explicit_priority_contradiction_raises_service_order_error() -> None:
    with pytest.raises(ServiceOrderError, match=r"contradicts its \"before\" constraint"):
        _ = Kernel("tests.fixtures.app_tagged_contradiction", bundles={}).build()


async def test_a_tagged_item_is_resolvable_by_its_type() -> None:
    compiled = Kernel("tests.fixtures.app_tagged_items", bundles={}).build()

    async with await compiled.boot() as booted:
        high = await booted.container.get(HighPriority, "high")
        low = await booted.container.get(LowPriority, "low")

    assert isinstance(high, HighPriority)
    assert isinstance(low, LowPriority)


async def test_a_collection_of_aliases_follows_the_tagged_order() -> None:
    compiled = Kernel("tests.fixtures.app_tagged_aliases", bundles={}).build()

    async with await compiled.boot() as booted:
        pipeline = await booted.container.get(Pipeline)

    assert pipeline.steps == ["Gamma", "Alpha", "Delta", "Beta"]
    assert pipeline.indexes == ["gamma", "alpha", "delta", "beta"]
