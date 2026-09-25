from __future__ import annotations

from xtr_dependency_injection.config.configure import configure
from xtr_dependency_injection.decorator.lifecycle import on_boot


@on_boot
@configure
def both() -> int:
    return 1
