"""Markers the kernel reads from scanned objects. Each only records; none has behaviour."""

from __future__ import annotations

from .as_alias import aliases_of, as_alias
from .as_decorator import AutowireDecorated, OnInvalid, as_decorator
from .as_service import as_service, service_of
from .as_tagged_item import TaggedItemMarker, as_tagged_item, tagged_item_of
from .autoconfigure import (
    AutoconfigureMarker,
    AutoconfigureTagMarker,
    autoconfigure,
    autoconfigure_of,
    autoconfigure_tag,
    autoconfigure_tags_of,
)
from .autowire import Autowire, Injected, is_container_supplied
from .compiler_pass import compiler_pass
from .exclude import exclude
from .lifecycle import on_boot, on_shutdown
from .remove_if_missing import remove_if_missing
from .target import Target
from .when import when, when_not

__all__ = [
    "AutoconfigureMarker",
    "AutoconfigureTagMarker",
    "Autowire",
    "AutowireDecorated",
    "Injected",
    "OnInvalid",
    "TaggedItemMarker",
    "Target",
    "aliases_of",
    "as_alias",
    "as_decorator",
    "as_service",
    "as_tagged_item",
    "autoconfigure",
    "autoconfigure_of",
    "autoconfigure_tag",
    "autoconfigure_tags_of",
    "compiler_pass",
    "exclude",
    "is_container_supplied",
    "on_boot",
    "on_shutdown",
    "remove_if_missing",
    "service_of",
    "tagged_item_of",
    "when",
    "when_not",
]
