from __future__ import annotations

import pytest

from tests.support.modules import scratch_modules

__all__ = ["scratch_modules"]

pytest_plugins = ["pytester"]

# Fixture packages are scanned by the tests, not collected: some of their
# modules raise on import, to prove a scan never imports them.
collect_ignore = ["fixtures"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
