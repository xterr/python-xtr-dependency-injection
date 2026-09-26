<div align="center">

# xtr-dependency-injection

**A bundle and kernel layer for Python, compiled to a wireup container.**

<img alt="python 3.11+" src="https://img.shields.io/badge/python-%E2%89%A5%203.11-3776AB?logo=python&logoColor=white">
<img alt="core dependencies: 3" src="https://img.shields.io/badge/core%20deps-3-3FB950">
<img alt="typed" src="https://img.shields.io/badge/typed-ty%20%2B%20basedpyright-1f6feb">
<img alt="license MIT" src="https://img.shields.io/badge/license-MIT-blue">

</div>

---

## Why?

Every library that wants to live in a container ends up shipping its own service-factory
helper, its own "import this before building the container" rule, and its own way of asking
whether a peer is there. The application then glues five of them together by hand.

This package gives each library one integration seam: **each library ships one bundle, the
application lists the bundles it wants, and everything else is one line.** It is not a
container: [wireup](https://github.com/maldoinc/wireup) is. This package decides *what* goes
into wireup, in *which order*, *for which environment*, and runs the lifecycle around it.

The runtime surface is a small Python API — `Bundle`, `ContainerBuilder`, `Definition`,
`ServiceConfigurator`, `PassStage`, `@autoconfigure`, `@as_decorator`, `@required_bundle`.
The engine is hidden behind `ContainerInterface` — the application, and every library that
ships a bundle, never imports wireup.

- 🐍 **Python-first configuration** — typed config objects and `@configure` functions, no files.
- 📜 **Listed and required** — the application lists root bundles in `<package>/bundles.py`; required peers arrive through `@required_bundle`.
- 🌗 **Per environment** — `@when("prod")` on anything scanned; a bundle activated only for `dev` never runs elsewhere.
- 🧱 **Per kernel** — two kernels in one process share no container, no registry, no import side effect.
- 🔍 **Explainable** — every bundle, config step and override is recorded, and printable.
- 🪶 **Three dependencies** — `wireup`, `typing-extensions` and `xtr-service-contracts`.

```python
kernel = Kernel("app")
```

## Install

```sh
uv add xtr-dependency-injection
```

Libraries depend on it through an extra, so using them without a container costs nothing:

```toml
[project.optional-dependencies]
di = ["xtr-dependency-injection>=1.0,<2"]
```

## The golden path

An application once the xtr libraries ship their bundles. Root bundles are listed in
`app/bundles.py`; clock, logging and console arrive because the messenger bundle requires them.

```python
# app/kernel.py
from xtr_dependency_injection import Kernel

kernel = Kernel("app")  # does no work; env from APP_ENV (default "dev"), debug from APP_DEBUG
```

```python
# app/bundles.py
from xtr_messenger.bundle import MessengerBundle

BUNDLES = {MessengerBundle: {"all": True}}
```

```python
# app/__main__.py
# async def console(application: Injected[Application]) -> int
from xtr_console.bundle import console

from app.kernel import kernel

raise SystemExit(kernel.run(console))
```

```python
# app/config/messenger.py
from dataclasses import replace

from xtr_dependency_injection import configure, env
from xtr_messenger import MessageBusConfig, TransportConfig

from app.billing.messages import IssueInvoice


@configure
def messenger(config: MessageBusConfig) -> MessageBusConfig:
    return replace(
        config,
        transports={"async": TransportConfig(env("MESSENGER_DSN"))},
        routing={IssueInvoice: "async"},
    )
```

```python
# app/billing/services.py
from xtr_dependency_injection import as_service


@as_service
class InvoiceRepository:
    def __init__(self, session: Session) -> None: ...
```

```python
# app/boot.py
from xtr_dependency_injection import Injected, on_boot


@on_boot
async def warm_cache(cache: Injected[Cache]) -> None: ...
```

That is the whole application. Other entry points use the same kernel:

```python
# FastAPI: the container must exist before the app is wired; boot hooks run in the lifespan
import wireup.integration.fastapi
from xtr_dependency_injection.integration.wireup import engine_container

compiled = kernel.build()
app = FastAPI(lifespan=compiled.lifespan)
wireup.integration.fastapi.setup(engine_container(compiled), app)

# a script or a worker
async with await kernel.boot() as booted:
    invoices = await booted.container.get(InvoiceRepository)
```

`build()` compiles; `boot()` also runs every bundle's `boot()` and the application's
`@on_boot` hooks; `run(main)` boots, calls `main` with its `Injected[...]` parameters filled,
shuts down, and returns `main`'s exit code. A `Kernel` is a recipe: every `build()` is
independent.

| Argument | Default | Meaning |
|---|---|---|
| `package` | — | The application package, scanned recursively |
| `env` / `debug` | `APP_ENV` or `"dev"` / `APP_DEBUG` or "not prod" | The environment built for |
| `name` | last component of `package` | The application's name |
| `bundles` | `<package>.bundles.BUNDLES` when defined, else `{}` | Root bundle classes mapped to per-environment activity flags |
| `resources` | `(package,)` | What to scan instead of `package` |
| `exclude` | `DEFAULT_EXCLUDES` | `fnmatch` patterns of modules never imported |
| `allowed_envs` | `None` | Refuse any other environment |

### Wiring bundles

An application lists root bundles in `<package>/bundles.py`. Each maps a class to per-env
activity flags: `{"all": True}` for every environment, `{"dev": True, "test": True}` when you
want that bundle only in development. **Installing a package does not activate a bundle**:
there is no entry-point discovery. If a bundle should be active, list it — or make another
active bundle require it.

```python
# app/bundles.py
from acme_debug.bundle import DebugBundle
from acme_mail.bundle import MailBundle

BUNDLES = {
    MailBundle: {"all": True},
    DebugBundle: {"dev": True, "test": True},
}
```

A bundle declares peers with the repeatable `@required_bundle` decorator. Required bundles
are pulled in recursively; a required class
inherits the requirer's activity in each environment. A string `"module:Class"` target is
imported lazily by the resolver, and with `ignore_on_invalid=True` is skipped silently when
its module is not installed.

```python
from xtr_dependency_injection import required_bundle
from acme_logging.bundle import LoggingBundle


@required_bundle(LoggingBundle)
@required_bundle("acme_metrics.bundle:MetricsBundle", ignore_on_invalid=True)
@as_bundle("mail", config=MailConfig)
class MailBundle(Bundle[MailConfig]): ...
```

The kernel bundle is always first, always active. Bundles are otherwise ordered by
`@required_bundle` topologically (a required bundle boots before its requirer), with ties
broken by name.

## Bundles for library authors

A bundle is the integration, never the library: the library keeps working without a container.

```python
# acme_mail/bundle/mail_bundle.py
from dataclasses import dataclass

from xtr_dependency_injection import (
    Bundle,
    ContainerBuilder,
    ServiceConfigurator,
    as_bundle,
)


@dataclass(frozen=True)
class MailConfig:
    host: str = "localhost"


@as_bundle("mail", config=MailConfig)
class MailBundle(Bundle[MailConfig]):
    def load_extension(
        self,
        config: MailConfig,
        services: ServiceConfigurator,
        builder: ContainerBuilder,
    ) -> None:
        def mailer(config: MailConfig) -> Mailer:
            return Mailer(host=config.host)

        _ = services.set(mailer)
        services.alias(MailerInterface, Mailer)
```

`@as_bundle(name, *, config=NoConfig, resources=())`:

- `name` is reserved: no two bundles may share it. `"kernel"` is the core bundle's.
- `config` is a config class buildable with no arguments; omit for `NoConfig` (nothing to
  configure).
- `resources` are scanned like the application. A bundle whose only job is to contribute
  commands or handlers is an empty class with `resources=("acme_tools.commands",)`.

The hooks, all optional, run in dependency order:

| Hook | Runs during | Purpose |
|---|---|---|
| `build(builder)` | step 4 | Compile-time wiring: compiler passes, autoconfiguration, kernel parameters |
| `prepend_extension(builder)` | step 5 (prepend) | Adjust other bundles' configs, using `builder.prepend_extension_config` |
| `load_extension(config, services, builder)` | step 6 (load) | Define services with `services.set` / `services.instance` / `services.alias` / `services.load` |
| `process(builder)` | step 10 | See and adjust every definition after every bundle has loaded |
| `async boot()` | after compile | Async I/O and handler binding — `self.container` is set |
| `async shutdown()` | reverse order | Async cleanup — `self.container` is still set |

In `boot` and `shutdown` the bundle reads the container from `self.container` — a
`ContainerInterface`, set by the kernel just before `boot`. **Fail at boot, not on first
use**: bind handlers and check signatures in `boot` when that is cheap.

The kernel registers every active bundle's resolved config under its type, so any service can
inject `MailConfig` directly. A bundle never registers its own config.

Each xtr library re-exports its config class from its `<pkg>.bundle` module alongside the
bundle, so an application configures it with a single import — `from xtr_messenger.bundle
import MessageBusConfig`, `from xtr_logging.bundle import LoggingConfig`, and likewise for
`xtr_clock.bundle` and `xtr_console.bundle`. All four do this.

### The zero-config contract

A package can arrive transitively, and *listed by another bundle* means *pulled in
automatically*. So with its default config a bundle must build and boot, do no I/O until a
service is requested, and never require the application to configure it. Every bundle's test
suite checks it:

```python
from xtr_dependency_injection.testing import assert_zero_config


async def test_mail_bundle_works_unconfigured() -> None:
    await assert_zero_config(MailBundle)
```

## Configuration

Configuration is Python. A config type is a frozen dataclass or msgspec `Struct` buildable
with no arguments; its `__post_init__` validates it. The application provides or transforms
it with `@configure`, told apart by the signature:

```python
@configure  # base: replaces the bundle's default
def mail() -> MailConfig:
    return MailConfig(host="smtp.internal")


@configure  # transform: receives the current value
@when("prod")
def mail_prod(config: MailConfig) -> MailConfig:
    return replace(config, host=env("SMTP_HOST"))
```

Each bundle's config resolves in one deterministic order, and every step is recorded:

1. the default, `MailConfig()`;
2. the application's base provider — one under `@when`/`@when_not` wins over an
   unconditional one;
3. `alias_of` forwards (see below), in bundle order;
4. other bundles' prepends, in bundle order (so they add to what the application chose);
5. the application's transforms — unconditional, then conditional; by `priority`, then scan
   order.

### Prepending from another bundle

A bundle adjusts a peer's config in `prepend_extension`, by name when the peer may not be
active — the builder skips a target that is not active and records that in the report:

```python
def prepend_extension(self, builder: ContainerBuilder) -> None:
    builder.prepend_extension_config("logging", add_channel("mail"))
```

`builder.prepend_extension_config(target, transform)` accepts a name (string) or a config
type. An unknown name / type is an error; an env-disabled target is skipped and reported.

### `AliasOf` — forwarding a config key

A bundle whose config exposes a field `Annotated[C | None, AliasOf("target")]` forwards its
non-`None` value to bundle `target`.
Configs then resolve in bundle topological order extended by owner → target edges. A conflict
with an app base provider raises `ConflictingConfigProvidersError` naming both sources.

```python
from typing import Annotated
from xtr_dependency_injection import AliasOf


@dataclass(frozen=True)
class MailConfig:
    host: str = "localhost"
    logging: Annotated[LoggingConfig | None, AliasOf("logging")] = None
```

### Parameters

**Parameters** are values injected with `Annotated[str, Autowire(param="...")]`. The kernel
provides `kernel.name`, `kernel.environment`, `kernel.debug`, `kernel.project_dir` and
`kernel.bundles` (a mapping of bundle name to `module:Class`); bundles add theirs with
`builder.set_parameter(name, value)`, the application with `@parameters`. They merge into
nested mappings and never override: a leaf set twice is a `ParameterConflictError` naming
both sources.

```python
from typing import Annotated
from xtr_dependency_injection import Autowire, as_service


@as_service
class Site:
    def __init__(self, name: Annotated[str, Autowire(param="kernel.name")]) -> None:
        self.name = name
```

### `env()`

`env(name, cast=str, *, default=...)` reads the environment while the kernel builds. It is
overloaded so the return type follows `cast` and `default`: `env("PORT", int)` is `int`,
`env("PORT", int, default=None)` is `int | None`, and `env("HOST")` is `str`. `bool` is the
one `cast` not applied as `bool(value)` (which is truthy for every non-empty string): it
reads `1/true/yes/on` for true and `0/false/no/off` or empty for false, case-insensitively.

```python
value: str | None = env("SMTP_PASSWORD", default=None)
port: int = env("SMTP_PORT", int, default=25)
```

Missing without a default raises `MissingEnvironmentVariableError`; a bad cast (including a
`bool` value that is neither true nor false) raises `InvalidEnvironmentVariableError`.

## Scanning and autoconfiguration

The kernel imports the application package — and every active bundle's `resources` — sorted
by name, skipping `*.tests`, `*.test_*`, `*.conftest` and `*.__main__`. It considers only the
functions and classes a module *defines*. Each goes to exactly one place:

| Found | Becomes |
|---|---|
| `@exclude` | nothing |
| `@when` / `@when_not` not matching | nothing, reported as skipped |
| `@configure`, `@parameters`, `@compiler_pass`, `@on_boot`, `@on_shutdown`, `@as_decorator` | that queue |
| `@as_service`, `@as_alias`, `@as_tagged_item` | a definition, and a service candidate |
| anything else | a service candidate |

Service candidates are what bundles' **autoconfigurators** see. There are two flavours:

`ContainerBuilder.register_for_autoconfiguration(type)` returns a rule that tags every
definition whose built type has `type` in `__mro__` (nominal, by base type). The core bundle
uses it for `ResetInterface`:

```python
def build(self, builder: ContainerBuilder) -> None:
    _ = builder.register_for_autoconfiguration(ResetInterface).add_tag(
        "kernel.reset",
        method="reset",
    )
```

`ContainerBuilder.register_attribute_for_autoconfiguration(reader, callback)` lets a bundle
find services by a marker it defines itself. The console bundle registers commands this way:

```python
def build(self, builder: ContainerBuilder) -> None:
    builder.register_attribute_for_autoconfiguration(commands_declared_on, register_command)
```

Applications reach the same effect through decorators put on a class or interface:

```python
from xtr_dependency_injection import autoconfigure, autoconfigure_tag


@autoconfigure(tags=[("app.plugin", {"category": "core"})])
class Plugin: ...


@autoconfigure_tag("app.strategy")
class Strategy: ...  # every subclass tagged app.strategy
```

`@autoconfigure(tags=..., lifetime=..., factory=...)`: a callable tag-attribute value is
called once per concrete built class and returns the attribute mapping; `factory` turns a
matched class definition into a factory definition.

A bundle can scan a module only when a peer is active: `services.load("pkg.commands")` in
`load_extension` runs after every bundle has loaded (the late scan).

## Definitions and compiler passes

`ContainerBuilder` — one method one purpose:

| Method | Does |
|---|---|
| `register(service, *, qualifier=, lifetime=)` | Register a new definition and return it |
| `set_definition(definition)` | Store a fully-built `Definition` |
| `get_definition(service, qualifier=)` | Fetch a definition by key |
| `has_definition(service, qualifier=)` | Test whether a definition exists |
| `find_definition(service, qualifier=)` | Resolve aliases and return the underlying definition |
| `remove_definition(service, qualifier=)` | Drop a definition |
| `get_definitions()` | All definitions |
| `set_alias(alias, target, *, alias_qualifier=, target_qualifier=)` | Point one key at another |
| `get_alias / has_alias / remove_alias` | Read / test / drop an alias |
| `has(service, qualifier=)` | Definition or alias present |
| `find_tagged_service_ids(tag)` | Every definition carrying a tag |
| `get_parameter / has_parameter / set_parameter` | Read / test / write a parameter |
| `add_compiler_pass(fn, *, stage=, priority=)` | Register a compiler pass at a stage |
| `register_for_autoconfiguration(type)` | Nominal autoconfiguration rule by base type |
| `register_attribute_for_autoconfiguration(reader, callback)` | Marker-based autoconfiguration |
| `prepend_extension_config(bundle, transform)` | Transform another bundle's config |
| `get_extension_config(bundle)` | Read another bundle's current config |

Inside `load_extension`, a bundle registers services on the `ServiceConfigurator`:

- `services.set(cls_or_factory, *, qualifier=, lifetime="singleton")`
- `services.instance(obj, *, qualifier=)` — provide `obj` itself under `(type(obj), qualifier)`
- `services.alias(alias, target, *, alias_qualifier=, target_qualifier=)`
- `services.load("some.module", another_module)` — late scan

Every `Definition` is mutable and carries: `key`, `provider`, `kind` (`"class"` / `"factory"`
/ `"instance"`), `lifetime`, `origin`, `tags`, `decorates`, `priority`, `before`, `after`.
Methods on it: `add_tag(name, **attributes)`, `has_tag(name)`, `get_tag(name)`,
`clear_tag(name)`, `set_decorated_service(target, *, qualifier=, priority=, on_invalid=)`.

### `PassStage`

Compiler passes run in five stages, priority descending within a stage:

```python
from xtr_dependency_injection import PassStage, compiler_pass


@compiler_pass(stage=PassStage.BEFORE_REMOVING, priority=10)
def drop_optional_debug_services(builder: ContainerBuilder) -> None: ...
```

The stages are: `BEFORE_OPTIMIZATION`, `OPTIMIZE`, `BEFORE_REMOVING`, `REMOVE`,
`AFTER_REMOVING`. Built-in passes: `OPTIMIZE` resolves decorations; `BEFORE_REMOVING` runs
`remove_if_missing`; `AFTER_REMOVING` validates aliases.

### `@remove_if_missing`

Drops a service when a peer it needs is absent. A service tagged this way (tag name
`container.remove_if_missing`) is dropped by the built-in `BEFORE_REMOVING` pass when any of
its conditions is unmet:

```python
from xtr_dependency_injection import as_service, remove_if_missing


@remove_if_missing(service=MetricsCollector)
@as_service
class MetricsMiddleware: ...


@remove_if_missing(class_="acme_metrics.transports:Prometheus")
@as_service
class PrometheusExporter: ...
```

`service=` / `class_=` / `package=` are each an independent condition, and any non-empty
combination may be given in one call (an empty call is a `TypeError`); the decorator is
repeatable, and every tag on a definition must hold for the definition to survive.

**Notes:**

- `service=`, `class_=` and `package=` are each their own condition, evaluated independently;
  any non-empty combination may be given in one call and every condition must hold.
- `class_` carries a trailing underscore because `class` is a Python keyword.
- There is no `parent_packages` condition.

## Overrides and decoration

The application overrides a bundle's service by defining the same key — silently, and
recorded in the report. Two bundles defining one key is an error unless one calls
`builder.set_definition(...)` in `process`.

A decorator takes a service's place and receives the original through
`Annotated[T, AutowireDecorated()]`:

```python
from typing import Annotated
from xtr_dependency_injection import AutowireDecorated, OnInvalid, as_decorator


@as_decorator(Mailer)
class LoggingMailer(Mailer):
    def __init__(
        self,
        inner: Annotated[Mailer, AutowireDecorated()],
        logger: LoggerInterface,
    ) -> None: ...
```

Decorations of one service apply by `priority`, highest first: the highest wraps the
original. The decorator gets the decorated service's lifetime, lives only under the target's
key, and the original stays out of every `Sequence[Mailer]`. A bundle does the same by
calling `services.set(LoggingMailer).set_decorated_service(Mailer)`.

When the target is missing, `on_invalid=OnInvalid.EXCEPTION` (the default) fails the build;
`OnInvalid.IGNORE` drops the decorator; `OnInvalid.NULL` keeps it under the target key with
`None` for its `AutowireDecorated` parameter — the annotation must allow `None`.

## Container access

The kernel-provided container implements `ContainerInterface` from `xtr-service-contracts`
(get / has by type plus qualifier, and named parameters):

```python
from xtr_service_contracts import ContainerInterface


async def use(container: ContainerInterface) -> None:
    mailer = await container.get(Mailer)
    special = await container.get(Mailer, "special")  # qualified
    if container.has(MetricsCollector):
        ...
    name = container.get_parameter("kernel.name")
```

Services are keyed by `(type, qualifier)`: every id is a type, and an optional qualifier
selects between multiple registrations of the same type.

`container.get(T)` returns a singleton directly. When the service is registered
(`container.has(T)` is true) but the engine cannot build it, `get` raises a
`ServiceResolutionError` whose `.reason` is the engine's own message and whose message reads
`failed to resolve <T>: <engine message>`, with the engine error kept as `__cause__`. A
`lifetime="scoped"` or `lifetime="transient"` service exists only inside a scope, so asking
for one from the container is refused: those services are built inside a scope, so resolve
them from an injected callable, or from `bind_callable(container, target, per_call_scope=True)`
— the `ServiceResolutionError` for a scope mismatch says exactly that.

A service that asks for a dependency the container has no definition for does not fail
obscurely at build: the compiler raises a `ContainerCompilationError` whose message reads
`<Owner>.<param> needs <Type>, which is not a registered service: mark it @as_service (or
alias it with @as_alias), or register it in a bundle's load_extension` — and `<Type>['q']`
when the dependency wanted a qualifier. The engine error stays reachable as `__cause__`, and
any origin notes the compiler attached (naming where each mentioned definition came from) are
preserved. The fix is the named `@as_service`, `services.set(...)` or alias — not a stack
trace from the engine.

Constructor injection uses our own markers, compiled to the engine:

```python
from typing import Annotated
from xtr_dependency_injection import Autowire, Injected, Target, as_service, on_boot


@as_service
class Reporter:
    def __init__(
        self,
        env: Annotated[str, Autowire(param="kernel.environment")],
        mailer: Annotated[Mailer, Target("smtp")],
    ) -> None: ...


@on_boot
async def warm(cache: Injected[Cache]) -> None:  # same as Annotated[Cache, Autowire()]
    ...
```

### `ServiceLocator`

A lazy `Mapping[Hashable, T]` (a `ServiceCollectionInterface`) that builds each entry only
when asked for it by name:

```python
from xtr_dependency_injection import ServiceLocator


def middleware_locator(container: ContainerInterface) -> ServiceLocator[Middleware]:
    return ServiceLocator(
        container,
        {"auth": (Middleware, "auth"), "log": (Middleware, "log")},
    )
```

`await locator.get("auth")` returns the service. `len(locator)`, `"auth" in locator`,
`locator.provided_services()` and `async for name, svc in locator` all work; an unknown name
raises `UnknownLocatorKeyError` (a `LookupError`).

### `bind_callable`

Returns an async function that calls a handler, a command or any callable with its
`Injected[...]` parameters filled. A class target is resolved from the container on first
call. What it needs is checked at bind time, so a bundle binding in `boot` fails at boot:

```python
from xtr_dependency_injection import bind_callable


bound = bind_callable(container, my_handler)
result = await bound(message)
```

## Lifecycle

```
build()     environment → bundles → early scan → build() of every bundle →
            configs (default → app base → alias_of → prepends → app transforms) →
            load_extension → late scan → app-marked definitions → autoconfigure →
            compiler passes by stage → compile
boot()      bundle.boot() in order → @on_boot (priority, then scan order)
shutdown()  @on_shutdown → bundle.shutdown() in reverse → container.close()
```

Hooks are injected: `Injected[...]` parameters are filled, sync or async. A boot that fails
shuts down what already booted and closes the container; a `BaseException` (including
`KeyboardInterrupt`) triggers the same rollback and propagates. Shutdown runs every step even
if one fails, and raises the failures together as an `ExceptionGroup`. A generator factory's
cleanup runs as the container closes; put cleanup that must survive an error in `finally`,
because wireup throws a scope's error into the generator.

### `kernel.reset`

Reset between messages. The core bundle calls
`builder.register_for_autoconfiguration(ResetInterface).add_tag("kernel.reset", method="reset")`,
so any service explicitly inheriting `ResetInterface` (from `xtr-service-contracts`) is reset
by `ServicesResetter` between messages. A service opts in explicitly with
`services.set(X).add_tag("kernel.reset", method="clear")`; only *built* services are tracked
and reset.

```python
from xtr_service_contracts import ResetInterface
from xtr_dependency_injection import ServicesResetter, as_service


@as_service
class Cache(ResetInterface):
    def reset(self) -> None: ...


async def between_messages(container: ContainerInterface) -> None:
    resetter = await container.get(ServicesResetter)
    await resetter.reset()
```

Ordering — `@as_tagged_item(index=, priority=, before=, after=)`: collection order = global
priority desc, ties broken by `before` / `after` constraints. A contradiction, unsatisfiable
bound or cycle raises `ServiceOrderError`.

## Testing

```python
from xtr_dependency_injection.testing import boot_for_test

async with await boot_for_test(kernel, overrides={Mailer: FakeMailer()}) as booted:
    ...
```

`boot_for_test` builds for the `test` environment and applies overrides before any boot hook
runs. Keys may be `Type` or `(Type, qualifier)` tuples. The opt-in pytest plugin provides
`booted_kernel` and `container` fixtures; override `xtr_kernel` to return your kernel:

```python
pytest_plugins = ["xtr_dependency_injection.testing.pytest_plugin"]


@pytest.fixture
def xtr_kernel() -> Kernel:
    return kernel
```

The plugin requires anyio's pytest plugin and `@pytest.mark.anyio` on async tests;
pytest-asyncio strict mode is unsupported.

## Diagnostics

`compiled.report` — also `KernelInterface.report` inside the container — records what the
build decided. `report.render()` prints it as plain-text tables:

```
Bundles
=======
Name    Source    State   Required  Class                                                       Reason
------  --------  ------  --------  ----------------------------------------------------------  ------
kernel  kernel    active  -         xtr_dependency_injection.kernel.kernel_bundle:KernelBundle
mail    listed    active  -         acme_mail.bundle:MailBundle

Configs
=======
Bundle  Steps                                                                Value
------  -------------------------------------------------------------------  ------------------------------------
kernel  default                                                              NoConfig()
mail    default -> base shop.config:mail -> transform shop.config:mail_prod  MailConfig(host='smtp.internal:465')
```

Render one section with `render("bundles" | "configs" | "definitions" | "scan")`. The console
bundle exposes them as `debug:bundles`, `debug:config` and `debug:container`.

## Plain wireup — `integration.wireup`

The module `xtr_dependency_injection.integration.wireup` is the **only** engine-facing public
module. It exports two helpers:

- one that runs the same pipeline the kernel does — bundle requirements, configs, load,
  autoconfigure, process — without scanning an application package, and returns the list of
  wireup service items to spread into `wireup.create_async_container(services=[...])`;
- `engine_container(kernel)`, which unwraps a compiled or booted kernel down to its
  `wireup.AsyncContainer` for framework integrations such as
  `wireup.integration.fastapi.setup(engine_container(compiled), app)`.

Bundle *classes* are listed (not instances); every listed class is active (`{"all": True}`
semantics), and required peers are pulled in recursively. Boot hooks do not run, and
parameters need the kernel — wireup's `config=` stays the caller's.

Everywhere else, the public API stays behind `ContainerInterface`.

## Concepts

| Concept | Our API | What it does |
|---|---|---|
| Bundle | `Bundle[ConfigT]` + `@as_bundle(...)`: `build` / `prepend_extension` / `load_extension` / `process` | One integration seam per library |
| Required peer | `@required_bundle(target, ignore_on_invalid=...)` | Pull another bundle in recursively |
| Root bundle list | `<package>/bundles.py` `BUNDLES = {Bundle: {"env": True}}` | The application picks its bundles, per environment |
| Bundle config | A typed config class buildable with no arguments; `__post_init__` validates | Configuration is Python, not files |
| Application config | `@configure` functions | Provide or transform a bundle's config |
| Environment gate | `@when("prod")` / `@when_not("prod")` | Skip a scanned object outside its environment |
| Parameters | `@parameters` / `env("X", int, default=...)` | Named values injected by key |
| Config forwarding | `Annotated[C \| None, AliasOf("target")]` | Send a config field to another bundle |
| Scanning | The kernel scan + `services.load(...)` | Discover services under a package |
| Nominal autoconfiguration | `builder.register_for_autoconfiguration(T)` | Tag every subclass of `T` |
| Marker autoconfiguration | `builder.register_attribute_for_autoconfiguration(reader, callback)` | Tag services by a marker a bundle defines |
| Class-level autoconfigure | `@autoconfigure(...)` / `@autoconfigure_tag(...)` | The application's equivalent, on a class |
| Registering services | `services.set` / `services.instance` / `services.alias` / `services.load` | The bundle's service-registration surface |
| Aliasing | `@as_alias(alias, *, qualifier=)` | One type reachable under another |
| Tagged ordering | `@as_tagged_item(index=, priority=, before=, after=)` | Deterministic collection order |
| Compiler pass stages | `PassStage.BEFORE_OPTIMIZATION / OPTIMIZE / BEFORE_REMOVING / REMOVE / AFTER_REMOVING` | Five stages, priority-ordered within each |
| Compiler passes | `Bundle.process(builder)` + `@compiler_pass(stage=, priority=)` | See and adjust every definition |
| Conditional removal | `@remove_if_missing(service= / class_= / package=)` | Drop a service when a peer is absent |
| Decoration | `@as_decorator(T, priority=, on_invalid=OnInvalid.*)` + `Annotated[T, AutowireDecorated()]` | Wrap a service and receive the original |
| Parameter and target injection | `Autowire(param=...)` / `Target(name)` | Inject a parameter, or select a qualified service |
| Tag collections | `Sequence[T]` / `Mapping[Hashable, T]` / `ServiceLocator` | Inject every tagged service, eagerly or lazily |
| Reset between messages | `builder.register_for_autoconfiguration(ResetInterface).add_tag("kernel.reset", method="reset")` | Rebind stateful services per message |
| Lifecycle | `async Bundle.boot()` / `async Bundle.shutdown()` reading `self.container`; `@on_boot` / `@on_shutdown` | Async startup and cleanup |
| Container access | `xtr_service_contracts.ContainerInterface` — kernel-provided | Get / has by type plus qualifier, plus named parameters |
| Lazy service map | `xtr_dependency_injection.ServiceLocator` | A `Mapping[Hashable, T]` that builds entries on demand |
| Diagnostics | `CompiledKernel.report`, `debug:*` commands | Inspect bundles, configs, definitions, scan |

### How our API behaves

- **Services are keyed by type plus an optional qualifier.** Every id is a class; two
  registrations of the same class are told apart by a string qualifier, and `Target(name)`
  picks one at an injection site.
- **`class_` in `@remove_if_missing` carries a trailing underscore** because `class` is a
  Python keyword.
- **`service=` / `class_=` / `package=`** in `@remove_if_missing` are each an independent
  condition, and any non-empty combination may be given in one call; every condition must
  hold for the service to survive.
- **`Autowire` selects by type**, not by a service id: an autowired dependency is chosen by
  its type plus an optional `Target` qualifier.
- **`@as_alias` is unconditional and every service is reachable**: gate a definition with
  `@when` / `@when_not` on the class instead of asking the alias to condition itself.
- **`env(name, bool)`** reads `1/true/yes/on` and `0/false/no/off` case-insensitively, so
  `env("DEBUG", bool)` on `"0"` is `False`, not truthy.
- **`container.get()` returns singletons directly**; a `lifetime="scoped"` / `"transient"`
  service must be resolved inside a scope. An unknown dependency is reported as a guided
  build error naming the service and the missing type, not an engine stack trace.
- **`@as_service` is explicit**: registration is opt-in per class, and there is no
  unused-service pruning.
- **`boot` and `shutdown` are async.**
- **No lazy proxies, no synthetic services, no abstract or parent definitions, no
  public/private pruning.**
- **Installing a package does not activate a bundle**: there is no entry-point discovery, so
  the application lists root bundles.

## Errors

Every error derives from `DependencyInjectionError` and carries its data as typed attributes.
`ServiceNotFoundError`, `ParameterNotFoundError` and `UnknownLocatorKeyError` are also
`LookupError`s, so a caller can catch either the specific type or the built-in.

| Error | Raised when |
|---|---|
| `BundleDefinitionError` | A bad `@as_bundle` / `@required_bundle`, a reserved name, a bundle or config not buildable with no arguments, two bundles sharing a config type, a bad `"module:Class"` target |
| `DuplicateBundleError` | Two bundles share a name |
| `MissingBundleError` | A required bundle is absent, skipped, excluded or disabled |
| `CircularBundleDependencyError` | Bundle dependencies loop |
| `InvalidEnvironmentError` | The environment is not in `allowed_envs` |
| `ResourceImportError` | A scanned module failed to import |
| `ConfigProviderError` | A bad `@configure` / `@parameters`, one found too late, `NoConfig` targeted, a bad parameter key, two queue markers on one object, an `alias_of` value of the wrong type |
| `UnknownConfigTypeError` | No active bundle owns a configured type |
| `ConflictingConfigProvidersError` | Two base providers, or an app base and an `alias_of`, in one group |
| `ParameterConflictError` | A parameter set twice |
| `MissingEnvironmentVariableError` / `InvalidEnvironmentVariableError` | `env()` |
| `DuplicateServiceError` | Two bundles, or two application definitions, claim one key |
| `UnknownServiceError` | `set_definition` / `remove_definition` / `decorate` / `alias` target nothing |
| `DecoratorSignatureError` | A decorator without exactly one `Annotated[T, AutowireDecorated()]` parameter of the decorated type |
| `ServiceOrderError` | `@as_tagged_item` `before` / `after` contradict a priority or cycle |
| `ContainerCompilationError` | The engine failed to compile the container |
| `ServiceResolutionError` | The engine failed to build a registered service |
| `ServiceNotFoundError` / `ParameterNotFoundError` | `container.get` / `get_parameter` miss (`LookupError`) |
| `BuilderPhaseError` / `BuilderFrozenError` | A builder operation in the wrong phase / after compilation |
| `KernelAlreadyBootedError` | A compiled kernel booted twice |
| `UnknownLocatorKeyError` | `ServiceLocator.get` with an unknown name (`LookupError`) |

## Known limitations

- **Global registries remain.** The libraries' decorators still fill their process-wide
  default registries, so a command name is registered at import: `@when("dev")` and
  `@when("prod")` commands of one name clash. Use distinct names.
- **Some library state is process-wide** across kernels: `Clock.set`, and messenger's
  message-name registry.
- **asyncio only** for `kernel.run`.
- **Annotations must be importable at runtime** wherever wireup or the kernel reads them —
  not under `TYPE_CHECKING`.
- **No entry-point bundle discovery** and no `bundles:sync` command.

## Development

Developed in the [python-xtr](https://github.com/xterr/python-xtr) monorepo, under
`packages/xtr-dependency-injection`; run the commands below from there. The
`python-xtr-dependency-injection` repository is a read-only copy, so send issues and pull
requests to the monorepo.

```sh
uv sync
uv run ruff check && uv run ruff format --check && uv run basedpyright && uv run ty check && uv run pytest
```

## License

MIT
