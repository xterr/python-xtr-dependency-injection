"""A fixture application: an interface and a class marked under it.

``Impl`` carries ``@as_service``, so the kernel registers it under its own
key while scanning. A bundle then autoconfigures the same class under
``Iface`` with a qualifier, to prove a class already defined under one key is
still registered under every other key a bundle asks for.
"""

from __future__ import annotations

from xtr_dependency_injection.decorator.as_service import as_service


class Iface:
    pass


@as_service()
class Impl(Iface):
    pass
