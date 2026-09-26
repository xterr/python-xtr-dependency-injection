"""Fixture: ``@autoconfigure(factory=…)`` replaces the class definition."""

from __future__ import annotations

from xtr_dependency_injection.decorator.as_service import as_service
from xtr_dependency_injection.decorator.autoconfigure import autoconfigure


class Product:
    def __init__(self, tag: str) -> None:
        self.tag: str = tag


def build_product() -> ProductViaFactory:
    """Build a ``ProductViaFactory`` bypassing its ``__init__`` — its tag is ``from-factory``."""
    built = ProductViaFactory.__new__(ProductViaFactory)
    built.tag = "from-factory"
    return built


@autoconfigure(factory=build_product)
@as_service()
class ProductViaFactory(Product):
    def __init__(self) -> None:
        super().__init__("from-class")
