"""Something set aside, for a package that is not installed, is needed all the same."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["SetAsideModuleUsedError"]


class SetAsideModuleUsedError(DependencyInjectionError):
    """An object of a set-aside module would be used: declared, or claimed by an active bundle.

    A module is set aside when a package it needs is not installed; nothing it
    defines is registered. That is only safe while nothing needs any of it,
    so an object that would be used fails the build instead of being dropped.
    """

    name: str
    use: str
    module: str
    missing: tuple[str, ...]
    through: str | None

    def __init__(
        self,
        name: str,
        use: str,
        *,
        module: str,
        missing: tuple[str, ...],
        through: str | None = None,
    ) -> None:
        """Record the object, what would use it, and why its module was set aside.

        Args:
            name: ``module:qualname`` of the object.
            use: What would use it, such as ``"@as_service"`` or
                ``"bundle 'console' would register it"``.
            module: The module it is defined in.
            missing: The packages that module needs and that are not installed.
            through: The set-aside module it needs them through, if any.
        """
        self.name = name
        self.use = use
        self.module = module
        self.missing = missing
        self.through = through
        packages = ", ".join(repr(package) for package in missing)
        needs = f"it imports {through!r}, which needs " if through is not None else "it needs "
        message = (
            f"{name} is used ({use}), but its module {module!r} was set aside: {needs}{packages}, "
            f"not installed here. Install what provides {packages}, or stop importing it from "
            f"{module!r}."
        )
        super().__init__(message)
