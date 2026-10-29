"""An environment folder is named after no environment the kernel allows."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["UnknownEnvironmentFolderError"]


class UnknownEnvironmentFolderError(DependencyInjectionError):
    """A subpackage of ``config.packages`` or ``config.routes`` is not an allowed environment.

    Every such subpackage is an environment folder, imported only in the
    environment it is named after; with ``allowed_envs`` set, a name outside
    them is a folder no build would ever import — most often a typo.

    Attributes:
        folder: The folder's dotted module name.
        allowed: The environments the kernel allows.
    """

    folder: str
    allowed: tuple[str, ...]

    def __init__(self, folder: str, allowed: tuple[str, ...]) -> None:
        """Record the folder and the environments it could have been named after."""
        self.folder = folder
        self.allowed = allowed
        environment = folder.rsplit(".", 1)[-1]
        message = (
            f"{folder} is an environment folder, but {environment!r} is not an allowed "
            f"environment (allowed: {', '.join(allowed)}); rename it after one of them, or "
            "move its modules up a level to apply them in every environment"
        )
        super().__init__(message)
