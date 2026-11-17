"""Turning an error into text, whatever the error does."""

from __future__ import annotations

__all__ = ["safe_repr", "safe_str"]


def safe_str(error: BaseException) -> str:
    """Return ``str(error)``, or a stand-in naming its class when ``__str__`` raises.

    An error is what a service — or a library under it — raised, never a
    reason for reporting it to fail: a second exception raised while
    describing the first would replace it.
    """
    try:
        return str(error)
    except Exception:  # noqa: BLE001 — whatever it raises, the failure is still reported
        return _stand_in(error)


def safe_repr(error: BaseException) -> str:
    """Return ``repr(error)``, or a stand-in naming its class when ``__repr__`` raises.

    Used for the notes added while a unit tears down, where a raise would
    replace the unit's own outcome.
    """
    try:
        return repr(error)
    except Exception:  # noqa: BLE001 — whatever it raises, the failure is still reported
        return _stand_in(error)


def _stand_in(error: BaseException) -> str:
    kind = type(error)
    return f"[unprintable {kind.__module__}.{kind.__qualname__}]"
