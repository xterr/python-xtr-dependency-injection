from __future__ import annotations

import pytest

from xtr_dependency_injection.bundle import Bundle, BundleMetadata, NoConfig, as_bundle
from xtr_dependency_injection.exception import BundleDefinitionError

pytestmark = pytest.mark.anyio


@as_bundle("sample")
class SampleBundle(Bundle):
    pass


class Undecorated(SampleBundle):
    pass


def test_metadata_is_what_as_bundle_recorded() -> None:
    assert SampleBundle.metadata() == BundleMetadata(name="sample", config=NoConfig)


def test_an_undecorated_subclass_has_no_metadata_of_its_own() -> None:
    with pytest.raises(BundleDefinitionError, match="not decorated with @as_bundle"):
        _ = Undecorated.metadata()


async def test_boot_and_shutdown_do_nothing_by_default() -> None:
    bundle = SampleBundle()

    await bundle.boot()
    await bundle.shutdown()


def test_no_config_is_built_with_no_arguments() -> None:
    assert NoConfig() == NoConfig()
