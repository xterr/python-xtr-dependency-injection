from __future__ import annotations

import pytest

from xtr_dependency_injection.builder import Definition, Origin
from xtr_dependency_injection.builder.conflict_policy import DefinitionStore
from xtr_dependency_injection.exception import DuplicateServiceError


class Mailer:
    pass


APP = Origin("app", "app:Mailer")
ALPHA = Origin("bundle", "alpha")
BETA = Origin("bundle", "beta")
KERNEL = Origin("kernel", "kernel")


def _definition(origin: Origin, provider: object = Mailer) -> Definition:
    return Definition((Mailer, None), provider, "class", "singleton", origin)


def test_the_app_overrides_a_bundle_and_the_override_is_recorded() -> None:
    store = DefinitionStore()
    store.add(_definition(ALPHA))

    store.add(_definition(APP))

    assert store.get((Mailer, None)) == _definition(APP)
    assert store.overrides_of((Mailer, None)) == (ALPHA,)


def test_a_bundle_arriving_after_the_app_is_outranked() -> None:
    store = DefinitionStore()
    store.add(_definition(APP))

    store.add(_definition(ALPHA))

    assert store.get((Mailer, None)) == _definition(APP)
    assert store.overrides_of((Mailer, None)) == (ALPHA,)


def test_the_app_overrides_the_kernel() -> None:
    store = DefinitionStore()
    store.add(_definition(KERNEL))

    store.add(_definition(APP))

    assert store.overrides_of((Mailer, None)) == (KERNEL,)


def test_two_bundles_conflict() -> None:
    store = DefinitionStore()
    store.add(_definition(ALPHA))

    with pytest.raises(DuplicateServiceError) as caught:
        store.add(_definition(BETA))

    assert (caught.value.first, caught.value.second) == (ALPHA, BETA)


def test_two_app_definitions_conflict() -> None:
    store = DefinitionStore()
    store.add(_definition(APP))

    with pytest.raises(DuplicateServiceError):
        store.add(_definition(Origin("app", "app:Other")))


def test_replace_is_allowed_between_bundles_and_recorded() -> None:
    store = DefinitionStore()
    store.add(_definition(ALPHA))

    store.replace(_definition(BETA, provider="other"))

    definition = store.get((Mailer, None))
    assert definition is not None
    assert definition.provider == "other"
    assert store.overrides_of((Mailer, None)) == (ALPHA,)


def test_definitions_keep_declaration_order() -> None:
    store = DefinitionStore()
    first = Definition((Mailer, "a"), Mailer, "class", "singleton", ALPHA)
    second = Definition((Mailer, "b"), Mailer, "class", "singleton", ALPHA)
    store.add(second)
    store.add(first)

    assert store.definitions() == (second, first)


def test_a_removed_definition_is_gone() -> None:
    store = DefinitionStore()
    store.add(_definition(ALPHA))

    store.remove((Mailer, None))

    assert store.get((Mailer, None)) is None
    assert store.definitions() == ()


def test_has_provider_matches_by_identity() -> None:
    store = DefinitionStore()
    store.add(_definition(ALPHA))

    assert store.has_provider(Mailer)
    assert not store.has_provider(object())


def test_update_changes_fields_without_an_override() -> None:
    store = DefinitionStore()
    store.add(_definition(ALPHA))

    store.update((Mailer, None), reset_method="reset")

    definition = store.get((Mailer, None))
    assert definition is not None
    assert definition.reset_method == "reset"
    assert store.overrides_of((Mailer, None)) == ()
