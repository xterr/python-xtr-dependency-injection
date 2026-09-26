"""Fixture app: a JSON placeholder embedded in a string."""

from __future__ import annotations

from dataclasses import replace

from tests.fixtures.app_env import MailConfig
from xtr_dependency_injection import configure, env


@configure
def mail(config: MailConfig) -> MailConfig:
    return replace(config, host=f"smtp://{env('json:MAIL_OPTIONS')}")
