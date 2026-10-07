"""Helpers a bundle uses at runtime, against the container the kernel built.

``ScopeFactory`` is the concrete the kernel registers under
``ScopeFactoryInterface``; a service injects the interface.
"""

from __future__ import annotations

from .bind_callable import bind_callable
from .env_var_loader_interface import EnvVarLoaderInterface
from .env_var_processor import EnvVarProcessor
from .env_var_processor_interface import EnvVarProcessorInterface
from .optional_service import optional_service
from .reference import Reference
from .scope_factory import ScopeFactory
from .scope_factory_interface import ScopeFactoryInterface
from .service_locator import ServiceLocator
from .services_resetter import ServicesResetter
from .unit_of_work import current_unit_of_work, unit_of_work

__all__ = [
    "EnvVarLoaderInterface",
    "EnvVarProcessor",
    "EnvVarProcessorInterface",
    "Reference",
    "ScopeFactory",
    "ScopeFactoryInterface",
    "ServiceLocator",
    "ServicesResetter",
    "bind_callable",
    "current_unit_of_work",
    "optional_service",
    "unit_of_work",
]
