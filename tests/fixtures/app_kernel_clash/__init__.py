"""A fixture app that tries to override a kernel-registered service."""

from __future__ import annotations

from xtr_dependency_injection.decorator.as_service import as_service
from xtr_dependency_injection.runtime.services_resetter import ServicesResetter


@as_service()
def rival_resetter() -> ServicesResetter:
    return ServicesResetter()
