"""The unit a library ships to integrate with the kernel.

A bundle is the integration, never the library: the library keeps working
without a container, and its bundle only decides what goes into one. Every
hook is optional; a bundle contributing nothing but scanned resources is an
empty class.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeAlias, final

from typing_extensions import TypeVar

from xtr_dependency_injection.exception import BundleDefinitionError

if TYPE_CHECKING:
    from wireup import AsyncContainer

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.service_configurator import ServiceConfigurator
    from xtr_dependency_injection.config.config_prepender import ConfigPrepender

    from .bundle_metadata import BundleMetadata

__all__ = ["METADATA_ATTRIBUTE", "AnyBundle", "Bundle", "NoConfig"]

METADATA_ATTRIBUTE = "__xtr_bundle__"
"""Where ``@as_bundle`` stores a bundle's :class:`BundleMetadata` on its class."""


@final
@dataclass(frozen=True, slots=True)
class NoConfig:
    """The config of a bundle that takes none. Never registered, never configurable."""


ConfigT = TypeVar("ConfigT", default=NoConfig)


class Bundle(Generic[ConfigT]):
    """Base class of every bundle; declare one with ``@as_bundle``.

    A bundle is built with no arguments — discovery builds it that way — and
    its hooks run in dependency order: ``prepend`` and ``load`` while the
    container is built, ``process`` once every bundle loaded, ``boot`` and
    ``shutdown`` around the container's life.
    """

    def prepend(self, configs: ConfigPrepender) -> None:
        """Adjust other bundles' configs before they are loaded. Does nothing by default."""
        del configs

    def load(self, config: ConfigT, services: ServiceConfigurator) -> None:
        """Define this bundle's services from its resolved config. Does nothing by default."""
        del config, services

    def process(self, builder: ContainerBuilder) -> None:
        """Inspect and adjust every definition, from every bundle. Does nothing by default."""
        del builder

    async def boot(self, container: AsyncContainer) -> None:
        """Run once the container is built, before the application. Does nothing by default.

        Fail here, not on first use: bind handlers and check signatures now
        when that is cheap.
        """
        del container

    async def shutdown(self, container: AsyncContainer) -> None:
        """Run as the kernel shuts down, before the container closes. Does nothing by default."""
        del container

    @classmethod
    def metadata(cls) -> BundleMetadata:
        """Return what ``@as_bundle`` recorded on this very class.

        Raises:
            BundleDefinitionError: If the class was not decorated; a subclass
                of a decorated bundle is a different bundle and needs its own.
        """
        metadata: BundleMetadata | None = vars(cls).get(METADATA_ATTRIBUTE)
        if metadata is None:
            raise BundleDefinitionError(
                f"{cls.__module__}:{cls.__qualname__}", "it is not decorated with @as_bundle"
            )
        return metadata


# A bundle of whichever config type: only each bundle knows its own, and a
# bundle's config appears in a parameter position, so no variance helps.
AnyBundle: TypeAlias = Bundle[Any]  # pyright: ignore[reportExplicitAny]
