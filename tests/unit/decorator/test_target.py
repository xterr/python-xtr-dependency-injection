"""``Target``: which of several services of one type a parameter receives."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from xtr_dependency_injection import Target

if TYPE_CHECKING:
    from collections.abc import Callable


def test_targets_compare_by_their_qualifier() -> None:
    assert Target("smtp") == Target("smtp")
    assert Target("smtp") != Target("http")


def test_a_target_is_hashable() -> None:
    assert len({Target("smtp"), Target("smtp"), Target(("mail", 2))}) == 2


def test_target_requires_a_name() -> None:
    with pytest.raises(TypeError):
        # Runtime call — the missing argument is what this test proves.
        _ = cast("Callable[[], Target]", Target)()
