"""Fetch a service only when the container provides it."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Hashable

    from xtr_service_contracts import ContainerInterface

__all__ = ["optional_service"]

_T = TypeVar("_T")


async def optional_service(
    container: ContainerInterface,
    service: type[_T],
    qualifier: Hashable | None = None,
) -> _T | None:
    """Return the service, or ``None`` when the container does not provide it.

    For a bundle whose services use a peer's only when that peer is active —
    a logger for their channel when the logging bundle is — without failing
    when it is not.
    """
    if not container.has(service, qualifier):
        return None

    return await container.get(service, qualifier)
