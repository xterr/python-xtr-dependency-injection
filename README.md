<div align="center">

# xtr-dependency-injection

**A Symfony-style bundle and kernel layer for Python, compiled to a wireup container.**

<img alt="python 3.11+" src="https://img.shields.io/badge/python-%E2%89%A5%203.11-3776AB?logo=python&logoColor=white">
<img alt="core dependencies: 2" src="https://img.shields.io/badge/core%20deps-2-3FB950">
<img alt="typed" src="https://img.shields.io/badge/typed-ty%20%2B%20basedpyright-1f6feb">
<img alt="license MIT" src="https://img.shields.io/badge/license-MIT-blue">

</div>

---

## Why?

Every library that wants to live in a container ends up shipping its own `injectables(...)`
helper, its own "import this before building the container" rule, and its own way of asking
whether a peer is there. The application then glues five of them together by hand.

This package does for Python what Symfony's bundles do for PHP: **each library ships one
bundle, installed bundles register themselves, and an application is one line.** It is not a
container — [wireup](https://github.com/maldoinc/wireup) is. It decides *what* goes into
wireup, in *which order*, *for which environment*, and runs the lifecycle around it.

- 🔌 **Installed means registered** — bundles are found through entry points; the app lists nothing.
- 🐍 **Python-first configuration** — typed config objects and `@configure` functions, no files.
- 🌗 **Per environment** — `@when("prod")` on anything scanned; an excluded object never exists.
- 🧱 **Per kernel** — two kernels in one process share no container, no registry, no import side effect.
- 🔍 **Explainable** — every bundle, config step and override is recorded, and printable.
- 🪶 **Two dependencies** — `wireup` and `typing-extensions`.

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

The target shape of an application once the xtr libraries ship their bundles — clock, logging,
console and messenger are discovered because they are installed:

```python
# app/kernel.py
from xtr_dependency_injection import Kernel

kernel = Kernel("app")  # does no work; env from APP_ENV (default "dev"), debug from APP_DEBUG
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
# app/billing/services.py — plain wireup
from wireup import injectable


@injectable
class InvoiceRepository:
    def __init__(self, session: Session) -> None: ...
```

```python
# app/boot.py
from wireup import Injected

from xtr_dependency_injection import on_boot


@on_boot
async def warm_cache(cache: Injected[Cache]) -> None: ...
```

That is the whole application. Other entry points use the same kernel:

```python
# FastAPI: the container must exist before the app is wired; boot hooks run in the lifespan
compiled = kernel.build()
app = FastAPI(lifespan=compiled.lifespan)
wireup.integration.fastapi.setup(compiled.container, app)

# a script or a worker
async with await kernel.boot() as booted:
    invoices = await booted.container.get(InvoiceRepository)
```

`build()` compiles; `boot()` also runs every bundle's `boot` and the application's `@on_boot`
hooks; `run(main)` boots, calls `main` with its `Injected[...]` parameters filled, shuts down,
and returns `main`'s exit code. A `Kernel` is a recipe: every `build()` is independent.

| Argument | Default | Meaning |
|---|---|---|
| `package` | — | The application package, scanned recursively |
| `env` / `debug` | `APP_ENV` or `"dev"` / `APP_DEBUG` or "not prod" | The environment built for |
| `name` | last component of `package` | The application's name |
| `bundles` | every discovered bundle | Exactly these (plus what they require) |
| `exclude_bundles` | `()` | Names to leave out |
| `bundle_envs` | `None` | Per-bundle environments, overriding the bundle's own |
| `resources` | `(package,)` | What to scan instead of `package` |
| `exclude` | `DEFAULT_EXCLUDES` | `fnmatch` patterns of modules never imported |
| `allowed_envs` | `None` | Refuse any other environment |

## Bundles for library authors

A bundle is the integration, never the library: the library keeps working without a container.

```python
# acme_mail/bundle/mail_bundle.py
from dataclasses import dataclass

from xtr_dependency_injection import Bundle, ServiceConfigurator, as_bundle


@dataclass(frozen=True)
class MailConfig:
    host: str = "localhost"


@as_bundle("mail", config=MailConfig, optional=("logging",))
class MailBundle(Bundle[MailConfig]):
    def load(self, config: MailConfig, services: ServiceConfigurator) -> None:
        services.factory(mailer)  # def mailer(config: MailConfig) -> Mailer
        services.resettable(Mailer)
```

```toml
[project.entry-points."xtr_dependency_injection.bundles"]
mail = "acme_mail.bundle:MailBundle"
```

`@as_bundle(name, *, config, requires, optional, envs, resources)`:

- `requires` must be active too; `optional` only orders this bundle after a peer that *is*
  active. Both name bundles, so naming an optional peer never imports it.
- `envs` keeps a bundle to some environments; `resources` are scanned like the application.
- A bundle whose only job is to contribute commands or handlers is an empty class with
  `resources=("acme_tools.commands",)`.

The hooks, all optional, run in dependency order: `prepend(configs)` adjusts other bundles'
configs, `load(config, services)` defines services, `process(builder)` sees and adjusts every
definition, and `boot(container)` / `shutdown(container)` run around the container's life.
**Fail at boot, not on first use**: bind handlers and check signatures in `boot` when that is
cheap.

The kernel registers every active bundle's resolved config under its type, so any service can
inject `MailConfig`. A bundle never registers its own config.

### The zero-config contract

A package can arrive transitively, and installed means registered. So with its default config
a bundle must build and boot, do no I/O until a service is requested, and never require the
application to configure it. Every bundle's test suite checks it:

```python
from xtr_dependency_injection.testing import assert_zero_config


async def test_mail_bundle_works_unconfigured() -> None:
    await assert_zero_config(MailBundle)
```

## Configuration

Configuration is Python. A config type is a frozen dataclass or msgspec Struct buildable with no
arguments; its `__post_init__` validates it. The application provides or transforms it with
`@configure`, told apart by the signature:

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
2. the application's base provider — one under `@when`/`@when_not` wins over an unconditional one;
3. other bundles' prepends, in bundle order (so they add to what the application chose);
4. the application's transforms — unconditional, then conditional; by `priority`, then scan order.

A bundle adjusts a peer's config in `prepend`, by name when the peer is optional:

```python
def prepend(self, configs: ConfigPrepender) -> None:
    if configs.has_bundle("logging"):
        configs.transform("logging", add_channel("mail"))
```

**Parameters** are values injected with `Inject(config="...")`. The kernel provides
`kernel.name`, `kernel.environment`, `kernel.debug` and `kernel.project_dir`; bundles add theirs
with `services.parameters(...)`, the application with `@parameters`. They merge into nested
mappings and never override: a leaf set twice is an error naming both sources.

`env(name, cast=str, *, default=...)` reads the environment while the kernel builds. `bool`
reads `1/true/yes/on` and `0/false/no/off`.

## Scanning and autoconfiguration

The kernel imports the application package — and every active bundle's `resources` — sorted by
name, skipping `*.tests`, `*.test_*`, `*.conftest` and `*.__main__`. It considers only the
functions and classes a module *defines*. Each goes to exactly one place:

| Found | Becomes |
|---|---|
| `@exclude` | nothing |
| `@when` / `@when_not` not matching | nothing, reported as skipped |
| `@configure`, `@parameters`, `@compiler_pass`, `@on_boot`, `@on_shutdown`, `@as_decorator` | that queue |
| wireup's `@injectable` | a definition, and a service candidate |
| anything else | a service candidate |

Service candidates are what bundles' **autoconfigurators** see. A bundle registers a reader and
an apply function; the console bundle, for instance, reads `@as_command` metadata and registers
each command — nothing else needs to know what a command is:

```python
services.autoconfigure(commands_declared_on, register_command)
```

A bundle can scan a module only when a peer is active: `services.scan("pkg.commands")` in
`load` runs after every bundle has loaded. Application services still use wireup's own
`@injectable`: DTOs, enums and exceptions are not services, and wireup validates everything it
is given.

## Overrides and decoration

The application overrides a bundle's service by defining the same key — silently, as in
Symfony, and recorded in the report. Two bundles defining one key is an error unless one
calls `builder.replace(...)` in `process`.

A decorator takes a service's place and receives the original:

```python
@as_decorator(Mailer)
class LoggingMailer(Mailer):
    def __init__(self, inner: Inner[Mailer], logger: LoggerInterface) -> None: ...
```

Decorations of one service apply by `priority`, highest first: the highest wraps the original.
The decorator gets the decorated service's lifetime, and the original stays out of every
`Sequence[Mailer]`. `builder.decorate(Mailer, LoggingMailer)` does the same from a bundle.

A `@compiler_pass` receives the `ContainerBuilder` after every bundle's `process`, to inspect
or change any definition before compilation.

## Lifecycle

```
build()     environment → bundles → scan → configs → load → late scan
            → declared definitions → autoconfigure → process → finalize → compile
boot()      bundle.boot() in order → @on_boot (priority, then scan order)
shutdown()  @on_shutdown → bundle.shutdown() in reverse → container.close()
```

Hooks are injected: `Injected[...]` parameters are filled, sync or async. A boot that fails shuts
down what already booted and closes the container. Shutdown runs every step even if one fails,
and raises the failures together as an `ExceptionGroup`. A generator factory's cleanup runs as
the container closes; put cleanup that must survive an error in `finally`, because wireup throws
a scope's error into the generator.

## Runtime helpers

- `bind_callable(container, target, *, per_call_scope=False)` returns a coroutine function
  calling a handler, a command or any callable with its `Injected[...]` parameters filled. A
  class target is resolved from the container on first call. What it needs is checked at bind
  time, so a bundle binding in `boot` fails at boot.
- `ServiceLocator(container, {name: key})` builds a service only when asked for by name.
- `ServicesResetter` resets every *built* resettable service; a worker calls
  `await resetter.reset()` between messages.

## Testing

```python
from xtr_dependency_injection.testing import boot_for_test

async with await boot_for_test(kernel, overrides={Mailer: FakeMailer()}) as booted:
    ...
```

`boot_for_test` builds for the `test` environment and applies overrides before any boot hook
runs. The opt-in pytest plugin provides `booted_kernel` and `container` fixtures; override
`xtr_kernel` to return your kernel:

```python
pytest_plugins = ["xtr_dependency_injection.testing.pytest_plugin"]


@pytest.fixture
def xtr_kernel() -> Kernel:
    return kernel
```

## Diagnostics

`compiled.report` — also `KernelInterface.report` inside the container — records what the
build decided. `report.render()` prints it as plain-text tables:

```
Bundles
=======
Name    Source      State   Requires  Optional  Class                                                       Reason
------  ----------  ------  --------  --------  ----------------------------------------------------------  ------
kernel  explicit    active  -         -         xtr_dependency_injection.kernel.kernel_bundle:KernelBundle
mail    discovered  active  -         -         acme_mail:MailBundle

Configs
=======
Bundle  Steps                                                                Value
------  -------------------------------------------------------------------  ------------------------------------
kernel  default                                                              NoConfig()
mail    default -> base shop.config:mail -> transform shop.config:mail_prod  MailConfig(host='smtp.internal:465')
```

Render one section with `render("bundles" | "configs" | "definitions" | "scan")`. The console
bundle exposes them as `debug:bundles`, `debug:config` and `debug:container`.

## Standalone wireup

Without a kernel, `injectables()` runs the same pipeline — no discovery, no application scan —
and returns what to give wireup:

```python
container = wireup.create_async_container(
    injectables=[
        app.services,
        *injectables(
            [MailBundle()], configs=[MailConfig(host="smtp.internal")], scan=["app.handlers"]
        ),
    ],
)
```

Required bundles must be listed. Boot hooks do not run, and parameters need the kernel, because
wireup's `config=` stays yours.

## Symfony mapping

| Symfony | xtr-dependency-injection |
|---|---|
| `AbstractBundle` | `Bundle[ConfigT]` + `@as_bundle(...)`: `prepend()` / `load()` |
| Bundle config tree | A typed config class with defaults; `__post_init__` validates |
| `config/packages/*.yaml` | `@configure` functions |
| `when@prod:` / `#[When]` / `#[WhenNot]` | `@when("prod")` / `@when_not("prod")` |
| `parameters:` / `%env(X)%` | `@parameters` / `env("X", int, default=...)` |
| Auto-registered component bundles | Entry-point discovery |
| `#[RequiredBundle(ignoreOnInvalid:)]` | `@as_bundle(requires=..., optional=...)` |
| `bundles.php` per env | `@as_bundle(envs=...)` + `Kernel(bundle_envs=...)` |
| `resource: '../src/'` + autoconfigure | The kernel scan + `services.autoconfigure(reader, apply)` |
| Compiler passes | `Bundle.process(builder)` + `@compiler_pass` |
| `decorates:` / `#[AsDecorator]` | `@as_decorator(T)` + `Inner[T]` |
| Tagged iterator / locator | `Sequence[T]` / `Mapping[Hashable, T]` / `ServiceLocator` |
| `kernel.reset` | `services.resettable(T)` + `ServicesResetter` |
| `Bundle::boot()` / `shutdown()` | `Bundle.boot(container)` / `shutdown(container)`; `@on_boot` / `@on_shutdown` |
| `debug:container` / `debug:config` | `CompiledKernel.report`, `debug:*` commands |

## Errors

Every error derives from `DependencyInjectionError` and carries its data as typed attributes:

| Error | Raised when |
|---|---|
| `BundleDefinitionError` | a bad `@as_bundle`, a reserved name, a bundle or config not buildable with no arguments, two bundles sharing a config type |
| `DuplicateBundleError` | two bundles or entry points share a name |
| `MissingBundleError` | a required bundle is absent, skipped, excluded or disabled |
| `CircularBundleDependencyError` | bundle dependencies loop |
| `InvalidEnvironmentError` | the environment is not in `allowed_envs` |
| `ResourceImportError` | a scanned module failed to import |
| `ConfigProviderError` | a bad `@configure`/`@parameters`, one found too late, `NoConfig` targeted, a bad parameter key, two queue markers on one object |
| `UnknownConfigTypeError` | no active bundle owns a configured type |
| `ConflictingConfigProvidersError` | two base providers in one group |
| `ParameterConflictError` | a parameter set twice |
| `MissingEnvironmentVariableError` / `InvalidEnvironmentVariableError` | `env()` |
| `DuplicateServiceError` | two bundles, or two application definitions, claim one key |
| `UnknownServiceError` | `replace`/`remove`/`decorate`/`resettable` target nothing |
| `DecoratorSignatureError` | a decorator without exactly one `Inner[T]` of the decorated type |
| `BuilderPhaseError` / `BuilderFrozenError` | a builder operation in the wrong phase / after compilation |
| `KernelAlreadyBootedError` | a compiled kernel booted twice |
| `UnknownLocatorKeyError` | `ServiceLocator.get` with an unknown name |

## Known limitations

- **Global registries remain.** The libraries' decorators still fill their process-wide
  default registries, so a command name is registered at import: `@when("dev")` and
  `@when("prod")` commands of one name clash. Use distinct names.
- **Some library state is process-wide** across kernels: `Clock.set`, and messenger's
  message-name registry.
- **asyncio only** for `kernel.run`.
- **Annotations must be importable at runtime** wherever wireup or the kernel reads them — not
  under `TYPE_CHECKING`.

## Development

Developed in the [python-xtr](https://github.com/xterr/python-xtr) monorepo, under
`packages/xtr-dependency-injection`; run the commands below from there. The `python-xtr-dependency-injection` repository is a
read-only copy, so send issues and pull requests to the monorepo.

```sh
uv sync
uv run ruff check && uv run ruff format --check && uv run basedpyright && uv run ty check && uv run pytest
```

## License

MIT
