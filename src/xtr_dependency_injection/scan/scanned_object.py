"""One function or class the scan found, and where it was found."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ScannedObject"]


@dataclass(frozen=True, slots=True)
class ScannedObject:
    """A function or class defined in a scanned module.

    Attributes:
        obj: The function or class.
        name: ``module:qualname``, as reports and errors show it.
        owner: The bundle whose resources it was found in; ``None`` for the
            application's.
        order: Its position across every scan of one build — the scan
            order that ties break by.
        in_environment_folder: Whether it was found in the application's
            folder for the current environment, so it applies after, and
            wins over, what the common modules declare.
    """

    obj: object
    name: str
    owner: str | None
    order: int
    in_environment_folder: bool = False
