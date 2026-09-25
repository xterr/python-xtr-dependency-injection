from __future__ import annotations

from xtr_dependency_injection.decorator.when import (
    matches_env,
    when,
    when_envs_of,
    when_not,
    when_not_envs_of,
)


def test_when_records_the_environments() -> None:
    @when("dev", "test")
    def seed() -> None: ...

    assert when_envs_of(seed) == frozenset({"dev", "test"})


def test_repeating_when_widens_the_set() -> None:
    @when("dev")
    @when("test")
    def seed() -> None: ...

    assert when_envs_of(seed) == frozenset({"dev", "test"})


def test_an_unmarked_object_matches_every_environment() -> None:
    def plain() -> None: ...

    assert when_envs_of(plain) is None
    assert matches_env(plain, "prod")


def test_when_keeps_an_object_to_its_environments() -> None:
    @when("dev")
    def seed() -> None: ...

    assert matches_env(seed, "dev")
    assert not matches_env(seed, "prod")


def test_when_not_leaves_an_object_out_of_its_environments() -> None:
    @when_not("prod")
    def debug() -> None: ...

    assert when_not_envs_of(debug) == frozenset({"prod"})
    assert not matches_env(debug, "prod")
    assert matches_env(debug, "dev")


def test_both_conditions_must_pass() -> None:
    @when("dev", "test")
    @when_not("test")
    def seed() -> None: ...

    assert matches_env(seed, "dev")
    assert not matches_env(seed, "test")


def test_a_subclass_does_not_inherit_the_condition() -> None:
    @when("dev")
    class Parent:
        pass

    class Child(Parent):
        pass

    assert when_envs_of(Child) is None


def test_the_decorated_object_is_returned_unchanged() -> None:
    def seed() -> None: ...

    assert when("dev")(seed) is seed
