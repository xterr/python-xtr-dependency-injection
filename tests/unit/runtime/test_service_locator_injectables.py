"""The synthesizer that turns definitions into lazy ``ServiceLocator[T]`` injectables.

The decisions — which types get a locator, the keys and scope each carries — are
tested off hand-built definitions, without an engine: each synthesized injectable
is a factory whose declared return names its ``ServiceLocator[T]`` and whose
container parameter names the scope it resolves in, and calling it with any
container yields a locator whose entry keys can be read directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast, get_args, get_origin

import pytest
from wireup import AsyncContainer, ScopedAsyncContainer

from xtr_dependency_injection import Injected, ServiceLocator
from xtr_dependency_injection.builder.definition import Definition, Origin
from xtr_dependency_injection.runtime.service_locator_injectables import (
    service_locator_injectables,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable

    from xtr_dependency_injection.builder.definition import Lifetime, ServiceKey

    class OnlyAtTypeCheck:
        """Named in an annotation but absent at runtime, so evaluating it raises."""


class Middleware:
    pass


class Other:
    pass


class Absent:
    pass


def _class_definition(
    service: type,
    qualifier: Hashable | None = None,
    *,
    lifetime: Lifetime = "singleton",
) -> Definition:
    return Definition(
        key=(service, qualifier),
        provider=service,
        kind="class",
        lifetime=lifetime,
        origin=Origin("app", "test"),
    )


def _factory_definition(provider: object, provides: type) -> Definition:
    return Definition(
        key=(provides, None),
        provider=provider,
        kind="factory",
        lifetime="singleton",
        origin=Origin("app", "test"),
    )


def _by_return(injectables: list[object]) -> dict[object, object]:
    return {cast("dict[str, object]", i.__annotations__)["return"]: i for i in injectables}


def _keys(injectable: object) -> list[Hashable]:
    factory = cast("Callable[..., ServiceLocator[object]]", injectable)
    return list(factory(container=object()).provided_services())


def _container_annotation(injectable: object) -> object:
    return cast("dict[str, object]", injectable.__annotations__)["container"]


def test_a_locator_is_synthesized_per_provided_type() -> None:
    definitions = [_class_definition(Middleware, "a"), _class_definition(Other)]

    provided = _by_return(service_locator_injectables(definitions))

    assert set(provided) == {ServiceLocator[Middleware], ServiceLocator[Other]}


def test_a_locators_keys_are_the_members_qualifiers_in_order() -> None:
    definitions = [
        _class_definition(Middleware, "logging"),
        _class_definition(Middleware, "tracing"),
    ]

    injectable = _by_return(service_locator_injectables(definitions))[ServiceLocator[Middleware]]

    assert _keys(injectable) == ["logging", "tracing"]


def test_a_member_with_no_qualifier_is_keyed_none() -> None:
    injectable = _by_return(service_locator_injectables([_class_definition(Other)]))[
        ServiceLocator[Other]
    ]

    assert _keys(injectable) == [None]


def test_a_singleton_only_locator_resolves_from_the_root_container() -> None:
    injectable = _by_return(service_locator_injectables([_class_definition(Middleware, "a")]))[
        ServiceLocator[Middleware]
    ]

    assert _container_annotation(injectable) is AsyncContainer


@pytest.mark.parametrize("lifetime", ["scoped", "transient"])
def test_a_non_singleton_member_makes_the_locator_resolve_from_the_scope(
    lifetime: Lifetime,
) -> None:
    definitions = [_class_definition(Middleware, "a", lifetime=lifetime)]

    injectable = _by_return(service_locator_injectables(definitions))[ServiceLocator[Middleware]]

    assert _container_annotation(injectable) is ScopedAsyncContainer


def test_a_type_that_is_itself_a_service_locator_gets_no_locator() -> None:
    locator_key: ServiceKey = (cast("type", cast("object", ServiceLocator[Middleware])), None)
    definition = Definition(
        key=locator_key,
        provider=lambda: None,
        kind="factory",
        lifetime="singleton",
        origin=Origin("app", "test"),
    )

    injectables = service_locator_injectables([definition])

    assert injectables == []


def test_a_user_provided_locator_is_not_overridden() -> None:
    def greeters() -> ServiceLocator[Middleware]:  # a definition already provides it
        raise NotImplementedError

    definitions = [
        _class_definition(Middleware, "a"),
        _factory_definition(greeters, cast("type", cast("object", ServiceLocator[Middleware]))),
    ]

    provided = _by_return(service_locator_injectables(definitions))

    assert ServiceLocator[Middleware] not in provided


def test_a_requested_type_with_no_members_yields_an_empty_locator() -> None:
    def consumer(locator: ServiceLocator[Absent]) -> None:
        del locator

    definitions = [_factory_definition(consumer, Other)]

    injectable = _by_return(service_locator_injectables(definitions))[ServiceLocator[Absent]]

    assert _keys(injectable) == []


def test_a_requested_type_is_found_through_injected_and_a_union() -> None:
    def consumer(
        one: Injected[ServiceLocator[Middleware]],
        two: ServiceLocator[Other] | None,
    ) -> None:
        del one, two

    provided = _by_return(service_locator_injectables([_factory_definition(consumer, Absent)]))

    assert ServiceLocator[Middleware] in provided
    assert ServiceLocator[Other] in provided


def test_a_provider_whose_signature_cannot_be_evaluated_is_skipped() -> None:
    def unresolvable(unknown: OnlyAtTypeCheck) -> None:
        del unknown

    definitions = [_factory_definition(unresolvable, Other)]

    provided = _by_return(service_locator_injectables(definitions))

    assert set(provided) == {ServiceLocator[Other]}  # only the member type, request skipped


def test_an_annotated_service_locator_argument_is_still_a_type_not_a_forward_ref() -> None:
    def consumer(locator: Annotated[ServiceLocator[Middleware], "meta"]) -> None:
        del locator

    provided = _by_return(service_locator_injectables([_factory_definition(consumer, Other)]))

    request = ServiceLocator[Middleware]
    assert request in provided
    assert get_origin(request) is ServiceLocator
    assert get_args(request) == (Middleware,)
