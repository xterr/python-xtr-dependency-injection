from __future__ import annotations

from itertools import pairwise

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.diagnostics import (
    BundleReport,
    ConfigReport,
    DefinitionReport,
    KernelReport,
    ScanReport,
)
from xtr_dependency_injection.diagnostics.report import ReportBuilder


class Mailer:
    pass


def _report() -> KernelReport:
    return KernelReport(
        bundles=(
            BundleReport("kernel", "x:KernelBundle", "kernel", "active"),
            BundleReport("alpha", "a:Alpha", "listed", "active", None, ("beta",)),
            BundleReport("gamma", "g:Gamma", "required", "skipped", "ImportError"),
        ),
        configs=(ConfigReport("alpha", 3, ("default", "base app.config:alpha")),),
        definitions=(
            DefinitionReport(
                key=(Mailer, "smtp"),
                provider_qualname="tests.Mailer",
                kind="class",
                lifetime="singleton",
                origin=Origin("app", "app.mail:Mailer"),
                overrides=(Origin("bundle", "alpha"),),
                decorated_by=("app.mail:Tracing",),
                tags=("kernel.reset",),
                aliases=("app.mail.MailerInterface",),
            ),
        ),
        scan=ScanReport(modules=("app", "app.mail"), skipped=(("app.dev:seed", "not in prod"),)),
    )


BUNDLES = """\
Bundles
=======
Name    Source    State    Required  Class           Reason
------  --------  -------  --------  --------------  -----------
kernel  kernel    active   -         x:KernelBundle
alpha   listed    active   beta      a:Alpha
gamma   required  skipped  -         g:Gamma         ImportError"""


def test_the_bundles_section_is_a_fixed_width_table() -> None:
    assert _report().render("bundles") == BUNDLES


CONFIGS = """\
Configs
=======
Bundle  Steps                             Value
------  --------------------------------  -----
alpha   default -> base app.config:alpha  3"""


def test_the_configs_section_shows_every_provenance_step() -> None:
    assert _report().render("configs") == CONFIGS


def test_the_definitions_section_shows_origin_overrides_and_decorators() -> None:
    rendered = _report().render("definitions")

    assert f"{__name__}.Mailer['smtp']" in rendered
    assert "app app.mail:Mailer" in rendered
    assert "bundle alpha" in rendered
    assert "app.mail:Tracing" in rendered


def test_the_definitions_section_lists_tags_and_aliases() -> None:
    rendered = _report().render("definitions")

    assert "Tags" in rendered
    assert "Aliases" in rendered
    assert "kernel.reset" in rendered
    assert "app.mail.MailerInterface" in rendered


def test_the_scan_section_lists_modules_and_skipped_objects() -> None:
    rendered = _report().render("scan")

    assert "app.mail" in rendered
    assert "app.dev:seed  not in prod" in rendered


def test_an_empty_table_says_none() -> None:
    assert KernelReport().render("bundles").endswith("(none)")


def test_rendering_everything_joins_every_section() -> None:
    lines = _report().render().splitlines()
    titles = [title for title, rule in pairwise(lines) if set(rule) == {"="}]

    assert titles == [
        "Bundles",
        "Configs",
        "Definitions",
        "Scan",
    ]


def test_the_builder_freezes_what_it_collected() -> None:
    builder = ReportBuilder()
    builder.modules.append("app")
    builder.skipped.append(("app:x", "why"))

    report = builder.freeze()

    assert report.scan == ScanReport(("app",), (("app:x", "why"),))
