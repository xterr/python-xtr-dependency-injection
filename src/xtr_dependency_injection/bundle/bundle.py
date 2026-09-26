r"""The unit a library ships to integrate with the kernel.

A bundle is the integration, never the library: the library keeps working
without a container, and its bundle only decides what goes into one. Every
hook is optional; a bundle contributing nothing but scanned resources is an
empty class.

The hooks are: ``build`` for compilation-time wiring,
``prepend_extension`` for adjusting other bundles' configs,
``load_extension`` for defining services, ``process`` for a
whole-container view once every bundle loaded, and ``boot`` / ``shutdown``
around the container's life — the last two taking their container from
``self.container``, set by the kernel before ``boot``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Generic, TypeAlias, final

from typing_extensions import TypeVar

from xtr_dependency_injection.exception import BundleDefinitionError
from xtr_dependency_injection.exception._naming import qualified_name

if TYPE_CHECKING:
    from xtr_service_contracts import ContainerInterface

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.service_configurator import ServiceConfigurator

    from .bundle_metadata import BundleMetadata
    from .required_bundle import RequiredBundle

__all__ = ["KERNEL_BUNDLE", "METADATA_ATTRIBUTE", "AnyBundle", "Bundle", "NoConfig"]

KERNEL_BUNDLE: Final = "kernel"
"""The core bundle's name: reserved, always active, always first."""

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
    its hooks run in dependency order: ``build`` and ``prepend_extension``
    while the container is being wired, ``load_extension`` while services are
    defined, ``process`` once every bundle loaded, ``boot`` and ``shutdown``
    around the container's life.

    Attributes:
        container: The container the bundle has been booted against, set by
            the kernel right before :meth:`boot` runs. It is ``None``
            outside a boot/shutdown cycle.
    """

    container: ContainerInterface | None = None

    def build(self, builder: ContainerBuilder) -> None:
        """Wire the container at compile time. Does nothing by default.

        Runs once per build, in bundle order, before any bundle's
        ``prepend_extension``. Register compiler passes or autoconfiguration
        rules here.
        """
        del builder

    def prepend_extension(self, builder: ContainerBuilder) -> None:
        """Adjust other bundles' configs before they are loaded. Does nothing by default.

        Call ``builder.prepend_extension_config(target, transform)`` for every
        adjustment.
        """
        del builder

    def load_extension(
        self, config: ConfigT, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        """Define this bundle's services from its resolved config. Does nothing by default."""
        del config, services, builder

    def process(self, builder: ContainerBuilder) -> None:
        """Inspect and adjust every definition, from every bundle. Does nothing by default."""
        del builder

    async def boot(self) -> None:
        """Run once the container is built, before the application. Does nothing by default.

        ``self.container`` is set by the kernel right before this runs.
        Fail here, not on first use: bind handlers and check signatures now
        when that is cheap.
        """

    async def shutdown(self) -> None:
        """Run as the kernel shuts down, before the container closes. Does nothing by default."""

    @classmethod
    def metadata(cls) -> BundleMetadata:
        """Return the metadata ``@as_bundle`` and ``@required_bundle`` recorded on this class.

        ``@required_bundle`` declarations are merged in at call time so their
        source order relative to ``@as_bundle`` does not matter.

        Raises:
            BundleDefinitionError: If the class was not decorated; a subclass
                of a decorated bundle is a different bundle and needs its own.
        """
        # Deferred imports break a circular dependency:
        # bundle_metadata -> required_bundle -> bundle.
        from .bundle_metadata import BundleMetadata as _BundleMetadata  # noqa: PLC0415
        from .required_bundle import required_bundles_of  # noqa: PLC0415

        stored: BundleMetadata | None = vars(cls).get(METADATA_ATTRIBUTE)
        if stored is None:
            raise BundleDefinitionError(qualified_name(cls), "it is not decorated with @as_bundle")
        extra: tuple[RequiredBundle, ...] = required_bundles_of(cls)
        if not extra:
            return stored
        return _BundleMetadata(
            name=stored.name,
            config=stored.config,
            resources=stored.resources,
            required=(*stored.required, *extra),
        )


# A bundle of whichever config type: only each bundle knows its own, and a
# bundle's config appears in a parameter position, so no variance helps.
AnyBundle: TypeAlias = Bundle[Any]  # pyright: ignore[reportExplicitAny]
