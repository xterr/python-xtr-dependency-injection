---
name: xtr-dependency-injection-bundle-authoring
description: How a library integrates with the xtr kernel by shipping one bundle — @as_bundle, a config type, the build / prepend_extension / load_extension / process / boot / shutdown hooks, ServiceConfigurator, @required_bundle, compiler passes, autoconfiguration, the zero-config contract and the bundles entry point. Use when writing or changing a library's bundle/ package, integrating a library with the kernel, registering a library's services or aliases, adding a bundle config field or validating one, adjusting a peer bundle's config, declaring a required or optional peer bundle, writing a compiler pass or choosing a PassStage, autoconfiguring services by base type or by a marker the library defines, dropping a service when a peer is absent, decorating another bundle's service, binding user callables through the container, advertising a bundle so debug:bundles can see it, or a bundle test fails assert_zero_config.
---

# xtr-dependency-injection-bundle-authoring

A library keeps working without a container. The bundle is the integration on top: it decides
what the library puts into the container, in which order, and for which environment. One
library, one bundle, no import side effects.

Wiring an *application* is a different job: load the skill `xtr-dependency-injection`.

## Quick reference

| Want | Write |
| --- | --- |
| Declare the bundle | `@as_bundle("mail", config=MailConfig)` on a `Bundle[MailConfig]` subclass |
| Scan extra modules | `@as_bundle("mail", config=..., resources=("acme_mail.commands",))` |
| Compile-time wiring | `def build(self, builder)` |
| Adjust a peer's config | `def prepend_extension(self, builder)` + `builder.prepend_extension_config(...)` |
| Register services | `def load_extension(self, config, services, builder)` |
| See every definition | `def process(self, builder)` |
| Async startup / cleanup | `async def boot(self)` / `async def shutdown(self)`, reading `self.container` |
| Hard peer | `@required_bundle(LoggingBundle)` |
| Optional peer | `@required_bundle("xtr_logging.bundle:LoggingBundle", ignore_on_invalid=True)` |
| Is a peer there? | `bundle_active(builder, "logging")` |
| A service only if present | `await optional_service(container, LoggerInterface, "mail")` |
| Prove zero config | `await assert_zero_config(MailBundle)` |

Everything is imported from `xtr_dependency_injection`; the testing helpers from
`xtr_dependency_injection.testing`.

Deeper material lives beside this file:

| Read | For |
| --- | --- |
| [references/container-builder.md](references/container-builder.md) | The `ContainerBuilder` and `Definition` surface, aliases, arguments, decoration, `@remove_if_missing` |
| [references/compiler-passes.md](references/compiler-passes.md) | `PassStage`, where a bundle's `process` runs, the built-in passes |
| [references/autoconfiguration.md](references/autoconfiguration.md) | Claiming services by base type, or by a marker the library defines |
| [references/config-and-parameters.md](references/config-and-parameters.md) | Config resolution order, `AliasOf`, parameters, `env()` placeholders, `Reference` |
| [references/lifecycle-and-helpers.md](references/lifecycle-and-helpers.md) | Boot order, `bind_callable`, `is_container_supplied`, units of work, `named_factory` |

## Package layout

```
src/acme_mail/
├── mailer.py              the library; knows nothing about a container
└── bundle/                flat, one concern per module
    ├── __init__.py        re-exports MailBundle and MailConfig
    ├── mail_bundle.py     the bundle class
    ├── mail_config.py     its config (+ mail_configs.py for a tagged union)
    └── drop_unused_pass.py  a compiler pass, when the bundle needs one
```

`bundle/__init__.py` re-exports both (`__all__ = ["MailBundle", "MailConfig"]`), so an
application configures the bundle with one import from `acme_mail.bundle`.

Depend on the kernel through an extra, and advertise the bundle so `debug:bundles` can name it
when an application installed the package and never listed it. Advertising activates nothing.

```toml
[project.optional-dependencies]
di = ["xtr-dependency-injection>=2.0,<3"]

[project.entry-points."xtr_dependency_injection.bundles"]
mail = "acme_mail.bundle:MailBundle"
```

## The config type

A frozen dataclass (or a msgspec `Struct`) buildable with no arguments. `@as_bundle` builds it
once at import, so a default that raises fails there, naming the bundle.

```python
# acme_mail/bundle/mail_config.py
@dataclass(frozen=True, slots=True)
class MailConfig:
    """What the mail bundle builds from."""

    host: str = "localhost"
    port: int = 25

    def __post_init__(self) -> None:
        """Refuse a combination the defaults cannot express."""
        if isinstance(self.port, int) and not 1 <= self.port <= 65535:
            msg = f"port must be between 1 and 65535, got {self.port}"
            raise ValueError(msg)
```

- The kernel registers the resolved config under its own type, so any service may inject
  `MailConfig`. Never register it yourself, and no two bundles may share one config type.
- A field may hold an `env()` placeholder, so guard a numeric check with `isinstance` as above:
  while the kernel builds, a placeholder stands in for its value.
- A bundle that configures nothing omits `config=`, gets `NoConfig`, and cannot be `@configure`d.

## The bundle class

```python
# acme_mail/bundle/mail_bundle.py
from typing_extensions import override
from xtr_dependency_injection import (
    Bundle,
    ContainerBuilder,
    ServiceConfigurator,
    as_bundle,
    required_bundle,
)

from acme_mail.mailer import Mailer, MailerInterface

from .mail_config import MailConfig

__all__ = ["MailBundle"]


@final
@required_bundle("xtr_logging.bundle:LoggingBundle", ignore_on_invalid=True)
@as_bundle("mail", config=MailConfig)
class MailBundle(Bundle[MailConfig]):
    """Registers the mailer the library provides."""

    @override
    def load_extension(
        self,
        config: MailConfig,
        services: ServiceConfigurator,
        builder: ContainerBuilder,
    ) -> None:
        """Register a Mailer from the config and expose it under its interface."""
        del builder
        _ = services.set(Mailer).set_arguments({"host": config.host, "port": config.port})
        services.alias(MailerInterface, Mailer)
```

`@as_bundle(name, *, config=None, resources=())`:

| Argument | Rules |
| --- | --- |
| `name` | Lowercase letters, digits and underscores, from a letter. Unique across every installed bundle; `"kernel"` is reserved |
| `config` | A type buildable with no arguments. `None` means `NoConfig` |
| `resources` | Non-empty module or package names, scanned like the application's |

The class itself must build with no arguments. Give it an `__init__(self) -> None` when it
needs per-kernel state (a registry, a restore callable), never a parameter.

## The hooks, and the one job of each

| Hook | Runs | Do only this |
| --- | --- | --- |
| `build(builder)` | before any config resolves | Register compiler passes, autoconfiguration rules, parameters |
| `prepend_extension(builder)` | while configs resolve | `builder.prepend_extension_config(target, transform)` |
| `load_extension(config, services, builder)` | while services are defined | `services.set` / `instance` / `alias` / `load` |
| `process(builder)` | `BEFORE_OPTIMIZATION`, priority -10000 | Read and adjust definitions once every bundle has loaded |
| `async boot()` | after the container compiled | Async I/O, handler binding, configuration checks |
| `async shutdown()` | reverse bundle order | Release what `boot` took |

Each hook is allowed only its own calls: `add_compiler_pass` outside `build`, or
`prepend_extension_config` outside `prepend_extension`, raises `BuilderPhaseError`. Nothing may
change after compilation (`BuilderFrozenError`).

`self.container` is a `ContainerInterface`, set by the kernel just before `boot` and still set
during `shutdown`. **Fail at boot, not on first use**: read the resolved config, check every
DSN and every `Reference`, bind every handler there.

```python
    @override
    async def boot(self) -> None:
        container = self.container
        if container is None:  # pragma: no cover — the kernel sets this before boot.
            message = "MailBundle.boot ran without a container"
            raise RuntimeError(message)
        config = await container.get(MailConfig)  # env() values resolved
        if not config.host:
            raise InvalidMailConfigError("mail needs a host")
```

## Registering services

`load_extension` receives a `ServiceConfigurator` scoped to this bundle, so every definition
records its origin.

| Call | Does |
| --- | --- |
| `services.set(cls, *, qualifier=, lifetime=)` | Register a class under its own type |
| `services.set(factory, ...)` | Register a function under its annotated return type |
| `services.instance(obj, *, qualifier=)` | Provide `obj` itself, keyed `(type(obj), qualifier)` |
| `services.alias(Alias, Target, *, alias_qualifier=, target_qualifier=)` | Make one key reach another |
| `services.load("acme_mail.commands")` | Scan a module late, once every bundle has loaded |

- `set` returns the `Definition`: chain `set_argument(name, value)`, `set_arguments(mapping)`,
  `add_tag(name, **attributes)`, `set_decorated_service(Target)`.
- Hand the config to a service with `set_argument`, so `debug:container` shows the value and a
  placeholder in it resolves when the service is built. A factory taking `MailConfig` works too.
- `lifetime` defaults to `"singleton"`; `"scoped"` and `"transient"` services live only in a scope.
- `services.load(...)` scans a module only when a peer is active. A late scan may not declare
  `@configure`, `@parameters` or `@compiler_pass`: put those in `resources`.

## Peers

```python
@required_bundle(LoggingBundle)                                       # hard: must be active
@required_bundle("acme_metrics.bundle:MetricsBundle",                 # lazy import
                 ignore_on_invalid=True)                              # skipped when absent
```

A required bundle is pulled in recursively and inherits the requirer's activity per
environment; it boots before its requirer. A hard peer that cannot be resolved is a
`MissingBundleError`. A bundle may not require itself.

Then branch on what actually arrived:

```python
    @override
    def prepend_extension(self, builder: ContainerBuilder) -> None:
        """Add the mail channel to logging's config, when logging is there."""
        if not bundle_active(builder, "logging"):
            return
        from xtr_logging.bundle import LoggingConfig  # noqa: PLC0415 — optional peer

        def add_mail_channel(config: LoggingConfig) -> LoggingConfig:
            return config.with_channels("mail")

        builder.prepend_extension_config(LoggingConfig, add_mail_channel)
```

- `bundle_active(builder, name)` answers from `build` onwards.
- `prepend_extension_config` takes a name or a config type. A target that is not active is
  skipped and recorded in the report; a name no bundle answers to is an error.
- Import an optional peer's types inside the branch, never at module level. Where even that is
  too much, pass the name and transform the config by duck typing.

## Testing

Every bundle's suite proves the zero-config contract: with its default config the bundle must
build, boot and shut down, require no application configuration, and do no I/O until a service
is asked for.

```python
# tests/unit/bundle/test_mail_bundle.py
import pytest
from xtr_dependency_injection.testing import assert_zero_config

from acme_mail.bundle import MailBundle


@pytest.mark.anyio
async def test_it_builds_and_boots_with_no_configuration() -> None:
    await assert_zero_config(MailBundle)
```

It builds a kernel of this bundle alone, for the `test` environment, scanning nothing; peers come
from `@required_bundle`. For anything richer, boot a kernel of your own and swap services, with
`boot_for_test`, which builds for `test` and installs overrides before any boot hook runs:

```python
kernel = Kernel("acme_mail", bundles={MailBundle: {"all": True}}, resources=())

async with await boot_for_test(kernel, overrides={Mailer: FakeMailer()}) as booted:
    mailer = await booted.container.get(MailerInterface)
```

An override key is a type or a `(type, qualifier)` pair. A `conftest.py` with an `anyio_backend`
fixture returning `"asyncio"` is all the async plumbing needed.

## Errors

Raise the library's own typed errors from a bundle; these are what the kernel raises at you:

| Error | Raised when |
| --- | --- |
| `BundleDefinitionError` | A bad or reserved name, a class that is not a `Bundle`, a bundle or config needing constructor arguments, a bad `"module:Class"` target, a bundle requiring itself |
| `DuplicateBundleError` | Two bundles share a name |
| `MissingBundleError` | A hard peer is absent, skipped or disabled |
| `CircularBundleDependencyError` | Requirements, or `AliasOf` forwards, loop |
| `BuilderPhaseError` / `BuilderFrozenError` | A builder call in the wrong hook / after compilation |
| `ConfigProviderError` / `UnknownConfigTypeError` | A prepend target takes no config / no active bundle owns a config type |
| `DuplicateServiceError` | Two bundles claim one key; resolve it in `process` with `set_definition` |
| `UnknownServiceError` | An alias, decoration or removal targets nothing |
| `InvalidDefinitionError` | A definition's provider, kind, key, lifetime or arguments disagree |

## Do not

- Do not make the library need the bundle: every class must be usable with plain constructor
  arguments, and the kernel extra must stay optional.
- Do not inject the container into a service. Declare what you need (`Injected[...]`,
  `Target(...)`, `Sequence[T]`, `Mapping[Hashable, T]`, `ServiceLocator[T]`), and register a
  service whose dependency may be absent only when it is there.
- Do not import `wireup`, anywhere. `ContainerInterface` is the whole runtime surface.
- Do not register the bundle's own config type; the kernel already did.
- Do not do I/O, read a file or open a connection in `build`, `load_extension` or at import.
- Do not defer a check to the first call when `boot` can make it.
- Do not read an environment variable yourself; put `env(...)` in the config and let the
  container resolve it where it is injected.
- Do not activate your own bundle from the package. An application lists it, or another active
  bundle requires it.
