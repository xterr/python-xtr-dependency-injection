"""Scanned late, only when the chorus bundle asks for it."""

from __future__ import annotations

from xtr_dependency_injection.decorator.as_service import as_service


@as_service()
class LateService:
    pass
