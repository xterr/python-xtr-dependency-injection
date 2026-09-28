"""The resolvers the injection markers hand the web framework."""

from __future__ import annotations

import types
from typing import TYPE_CHECKING

import pytest

from xtr_dependency_injection.integration.fastapi import provider

if TYPE_CHECKING:
    from typing import Literal


class Service:
    """A service type a resolver is derived for."""


def _named(resolver: object) -> str:
    assert isinstance(resolver, types.FunctionType)
    return resolver.__name__


def test_one_resolver_per_kind_key_and_qualifier() -> None:
    assert provider("service", Service, None) is provider("service", Service, None)
    assert provider("service", Service, "a") is not provider("service", Service, None)
    assert provider("param", "kernel.name") is provider("param", "kernel.name")
    assert provider("env", "int:PORT") is not provider("param", "int:PORT")


def test_a_resolver_is_flagged_and_named() -> None:
    resolve = provider("param", "kernel.name")

    assert getattr(resolve, "__xtr_provider__", False) is True
    assert _named(resolve) == "xtr_param[kernel.name]"
    assert _named(provider("service", Service, None)) == "xtr_service[Service]"


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["service", "param", "env"])
async def test_a_resolver_without_a_served_application_says_so(
    kind: Literal["service", "param", "env"],
) -> None:
    resolve = provider(kind, "unserved")

    with pytest.raises(RuntimeError, match="no kernel serves this application"):
        _ = await resolve()
