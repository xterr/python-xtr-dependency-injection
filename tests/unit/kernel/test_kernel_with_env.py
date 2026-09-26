"""Tests for Kernel.with_env behavior with explicit debug."""

from __future__ import annotations

import pytest  # noqa: TC002 — monkeypatch is used at runtime.

from xtr_dependency_injection import Kernel


class TestWithEnvDebug:
    """Test that with_env preserves or overrides debug correctly."""

    def test_with_env_keeps_an_explicit_debug(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When debug is explicitly set, with_env preserves it unless overridden."""
        # Given: a kernel with explicit debug=True and APP_DEBUG set to 0 (to trigger the bug)
        monkeypatch.setenv("APP_DEBUG", "0")
        kernel = Kernel("json", debug=True, resources=())

        # When: we call with_env without a debug argument
        new_kernel = kernel.with_env("test")

        # Then: the explicit debug carries over (not overridden by APP_DEBUG)
        assert new_kernel.debug is True

    def test_with_env_debug_argument_wins(self) -> None:
        """When with_env receives an explicit debug, it overrides the kernel's."""
        # Given: a kernel with explicit debug=True
        kernel = Kernel("json", debug=True, resources=())

        # When: we call with_env with debug=False
        new_kernel = kernel.with_env("test", debug=False)

        # Then: the with_env argument wins
        assert new_kernel.debug is False

    def test_with_env_without_any_debug_derives_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When neither kernel nor with_env has explicit debug, it derives from environment."""
        # Given: no explicit debug anywhere and APP_DEBUG unset
        monkeypatch.delenv("APP_DEBUG", raising=False)
        kernel = Kernel("json", resources=())  # no debug argument

        # When: we call with_env("prod") without a debug argument
        new_kernel = kernel.with_env("prod")

        # Then: debug derives from the environment (prod -> False)
        assert new_kernel.debug is False
