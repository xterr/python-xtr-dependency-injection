"""A fixture application providing parameters and nothing else."""

from __future__ import annotations

from xtr_dependency_injection.config.parameters import parameters


@parameters
def provided() -> dict[str, object]:
    return {"app": {"name": "fixture"}}
