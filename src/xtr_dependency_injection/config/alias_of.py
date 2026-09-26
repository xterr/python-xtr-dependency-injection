"""A bundle config field forwarding its value to another bundle's config.

A field on bundle ``A`` typed
``Annotated[TConfig | None, AliasOf("target")] = None`` sends its value, when
not ``None``, to the config of bundle ``target`` — right after ``target``'s
own app base step. The forwarding is recorded as a distinct
``alias_of <A>.<field>`` step in the diagnostics report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, cast, get_args, get_origin, get_type_hints

__all__ = ["AliasOf", "alias_of_fields"]


@dataclass(frozen=True, slots=True)
class AliasOf:
    """Mark a config field as forwarding its value to another bundle's config.

    Attributes:
        bundle: The name of the target bundle receiving the value.
    """

    bundle: str


def alias_of_fields(config_type: type) -> list[tuple[str, str]]:
    """Return ``(field_name, target_bundle)`` for every ``AliasOf``-annotated field.

    Fields typed anything but ``Annotated[..., AliasOf(...)]`` are ignored.
    Only the first ``AliasOf`` on a field counts. Types whose annotations
    cannot be resolved at runtime yield an empty list — the config resolver
    will fail later with a clearer message if needed.
    """
    try:
        raw_hints = get_type_hints(config_type, include_extras=True)
    except Exception:  # noqa: BLE001 — an unresolvable annotation is not this helper's failure.
        return []
    hints = cast("dict[str, object]", raw_hints)
    found: list[tuple[str, str]] = []
    for name, annotation in hints.items():
        if get_origin(annotation) is not Annotated:
            continue
        parts = cast("tuple[object, ...]", get_args(annotation))
        for entry in parts[1:]:
            if isinstance(entry, AliasOf):
                found.append((name, entry.bundle))
                break
    return found
