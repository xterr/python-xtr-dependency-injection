"""Declaring a bundle class."""

from __future__ import annotations

import inspect
import re
from typing import TYPE_CHECKING, Final, TypeVar, cast

from xtr_dependency_injection.exception import BundleDefinitionError

from .bundle import KERNEL_BUNDLE, METADATA_ATTRIBUTE, AnyBundle, Bundle, NoConfig
from .bundle_metadata import BundleMetadata

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ["as_bundle", "declare_bundle"]

B = TypeVar("B", bound=type[AnyBundle])

_NAME: Final = re.compile(r"^[a-z][a-z0-9_]*$")
_RESERVED: Final = frozenset({KERNEL_BUNDLE})


def as_bundle(
    name: str,
    /,
    *,
    config: type[object] | None = None,
    resources: Sequence[str] = (),
) -> Callable[[B], B]:
    """Declare the decorated ``Bundle`` subclass as the bundle ``name``.

    Args:
        name: Lowercase letters, digits and underscores, starting with a
            letter. ``KERNEL_BUNDLE`` is reserved.
        config: The config type ``load_extension`` receives: a frozen
            dataclass or msgspec Struct buildable with no arguments.
            ``None`` means ``NoConfig``.
        resources: Modules or packages scanned like the application's.

    Raises:
        BundleDefinitionError: If the name is invalid or reserved, the class
            is not a ``Bundle``, or it or its config cannot be built with no
            arguments.
    """
    if name in _RESERVED:
        raise BundleDefinitionError(name, "the name is reserved")
    for index, resource in enumerate(resources):
        if not isinstance(resource, str) or not resource:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise BundleDefinitionError(
                name, f"resources[{index}] must be a non-empty string, got {resource!r}"
            )
    return declare_bundle(
        BundleMetadata(
            name=name,
            config=config if config is not None else NoConfig,
            resources=tuple(resources),
        )
    )


def declare_bundle(metadata: BundleMetadata) -> Callable[[B], B]:
    """Return the decorator recording ``metadata``, after validating it — reserved names allowed."""
    if not _NAME.match(metadata.name):
        raise BundleDefinitionError(
            metadata.name, "a name is lowercase letters, digits and underscores, from a letter"
        )
    _check_config_default(metadata.name, metadata.config)

    def declare(cls: B) -> B:
        declared = cast("object", cls)
        if not (isinstance(declared, type) and issubclass(declared, Bundle)):
            raise BundleDefinitionError(metadata.name, f"{cls!r} is not a Bundle subclass")
        _check_no_argument_constructor(metadata.name, cls)
        _check_no_self_requirement(metadata.name, cls)
        setattr(cls, METADATA_ATTRIBUTE, metadata)
        return cls

    return declare


def _check_config_default(bundle: str, config: type[object]) -> None:
    """Refuse a config type that cannot be built with no arguments.

    The kernel builds it as the bundle's default anyway; failing here names
    the bundle at import instead of at the first build.
    """
    try:
        _ = config()
    except Exception as error:
        failure = BundleDefinitionError(bundle, "its config type cannot be built with no arguments")
        raise failure from error


def _check_no_self_requirement(bundle: str, cls: type[AnyBundle]) -> None:
    """Refuse a ``@required_bundle`` declaration that targets the bundle itself.

    A class target matching ``cls`` or a string target ``"module:ClassName"``
    whose module + qualname match ``cls`` — checked before the resolver runs
    so the failure names the class at import.
    """
    from .required_bundle import required_bundles_of  # noqa: PLC0415 — avoid an import cycle.

    self_name = f"{cls.__module__}:{cls.__qualname__}"
    for declaration in required_bundles_of(cls):
        target = declaration.target
        if target is cls or (isinstance(target, str) and target == self_name):
            raise BundleDefinitionError(bundle, "a bundle cannot list itself as a required_bundle")


def _check_no_argument_constructor(bundle: str, cls: type[object]) -> None:
    """Refuse a bundle class whose constructor requires arguments.

    Checked by signature only: building it here would run a library's
    constructor at import.
    """
    try:
        _ = inspect.signature(cls).bind()
    except TypeError as error:
        failure = BundleDefinitionError(bundle, "the bundle class requires constructor arguments")
        raise failure from error
