"""The resolvers the injection markers hand the web framework.

A marker that names a parameter, an environment variable or a service becomes
a framework dependency whose ``dependency`` is one resolver from here — one
per ``(kind, key, qualifier)``, cached so equal markers stay equal. Serving an
application takes the HTTP kernel package on top: until its setup call
attaches a kernel, a resolver that runs can only say what is missing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Hashable
    from typing import Literal

__all__ = ["provider"]

_NO_KERNEL: Final = (
    "this route asks the container for a dependency, but no kernel serves "
    "this application: call xtr_http_kernel.setup(app, kernel)"
)

_PROVIDERS: Final[dict[tuple[str, object, object], Callable[[], Awaitable[object]]]] = {}


def provider(
    kind: Literal["service", "param", "env"],
    key: object,
    qualifier: Hashable | None = None,
) -> Callable[[], Awaitable[object]]:
    """Return the resolver for one injection — the same one every time.

    One callable per ``(kind, key, qualifier)``: the framework tells route
    dependencies apart by the callable it was handed, and two equal markers
    must carry the same resolver to stay equal and hashable.
    """
    cache_key = (kind, key, qualifier)
    cached = _PROVIDERS.get(cache_key)
    if cached is not None:
        return cached

    async def resolve() -> object:
        raise RuntimeError(_NO_KERNEL)

    label = key.__qualname__ if isinstance(key, type) else str(key)
    resolve.__name__ = f"xtr_{kind}[{label}]"
    resolve.__qualname__ = resolve.__name__
    # ``set_dependency`` tells an already-derived resolver apart by this flag.
    resolve.__dict__["__xtr_provider__"] = True
    # ``setdefault`` keeps one canonical resolver even if two threads raced here.
    return _PROVIDERS.setdefault(cache_key, resolve)
