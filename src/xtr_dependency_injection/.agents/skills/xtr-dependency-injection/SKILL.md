---
name: xtr-dependency-injection
description: How to build and run an application on the xtr kernel and container — Kernel, the BUNDLES list, @configure functions, env() placeholders, parameters, @as_service and the injection markers, boot and shutdown hooks, units of work, testing and the debug commands. Use when writing or changing an application's kernel.py, bundles.py or config/ modules; adding or removing an xtr package; registering, aliasing, decorating or qualifying a service; injecting a parameter, an environment variable, a Sequence, a Mapping or a ServiceLocator; wiring a console, worker or FastAPI entry point; a service is not found, a bundle is installed but does nothing, a scoped service is refused, or a config value is a placeholder instead of a value.
---

# xtr-dependency-injection

A kernel that decides what goes into the container, in which order, and for which
environment. Each library ships one bundle; the application lists the bundles it wants, marks
its own classes `@as_service`, and configures everything in Python.

Writing a bundle for a library is a different job: load the skill
`xtr-dependency-injection-bundle-authoring`.

## Quick reference

| Want | Write |
| --- | --- |
| The kernel | `kernel = Kernel("app")` in `app/kernel.py` |
| Activate a bundle | `BUNDLES = {XBundle: {"all": True}}` in `app/bundles.py` |
| Configure a bundle | `@configure` in `app/config/<bundle>.py`, returning its config type |
| Register a class | `@as_service` (also `lifetime=`, `qualifier=`) |
| Inject a service | a plain annotated parameter in a service; `Injected[T]` in a hook, command, handler or route |
| Inject a qualified one | `Annotated[T, Target("smtp")]` |
| Inject a parameter | `Annotated[str, Autowire(param="kernel.name")]` |
| Inject a variable | `Annotated[int, Autowire(env="int:PORT")]` |
| Read a variable in config | `env("SMTP_HOST")`, `env("PORT", int, default=25)` |
| Run code at startup | `@on_boot` / `@on_shutdown` |
| Share a scope | `async with unit_of_work(container) as unit:` |
| Boot it | `kernel.run(main)`, `await kernel.boot()`, or `setup(app, kernel)` for HTTP |
| Check it | `debug:bundles`, `debug:config`, `debug:container` |

Imports come from `xtr_dependency_injection`; a bundle and its config come from
`<package>.bundle`.

## Application layout

```
app/
├── kernel.py        the Kernel recipe — the one line every entry point shares
├── bundles.py       BUNDLES: the root bundles, per environment
├── config/          one @configure module per bundle, plus @parameters
├── __main__.py      the console entry point
├── web/app.py       the HTTP entry point (xtr-http-kernel)
└── …                one package per concern; every module is scanned
```

```python
# app/kernel.py
from xtr_dependency_injection import Kernel

kernel = Kernel("app", allowed_envs=("dev", "test", "prod"))
```

`Kernel(...)` does no work: it stores a recipe, and every `build()` is independent. The
environment comes from `APP_ENV` (default `dev`), debug from `APP_DEBUG` (default: not prod).
Other arguments: `name`, `bundles`, `resources`, `exclude`, `environ`, `allowed_envs`.

```python
# app/bundles.py
from xtr_console.bundle import ConsoleBundle
from xtr_logging.bundle import LoggingBundle

BUNDLES = {
    LoggingBundle: {"all": True},
    ConsoleBundle: {"all": True},
    DebugBundle: {"dev": True, "test": True},
}
```

**Installing a package activates nothing.** A bundle is active because it is listed here, or
because an active bundle requires it. An environment named explicitly beats `"all"`, so
`{"all": True, "prod": False}` is everywhere but prod.

Entry points, all on the same kernel:

```python
raise SystemExit(kernel.run(console))  # console: boot, call, shut down, exit code
async with await kernel.boot() as booted:
    ...  # a script or a worker
setup(app, kernel)  # HTTP — from xtr_http_kernel
```

`build()` compiles, `boot()` also runs bundle boots and `@on_boot`, `run(main)` does both and
returns `main`'s exit code. Load `.env` files with xtr-dotenv at the entry point, before the
kernel is built. For the HTTP side read the `xtr-http-kernel` skill.

## Register a service

```python
from xtr_dependency_injection import as_alias, as_service


@as_service
class Mailer:
    def send(self, body: str) -> str: ...


@as_alias(Mailer, qualifier="smtp")
@as_service
class SmtpMailer(Mailer): ...
```

- Registration is opt-in: an unmarked class is never a service.
- Services are keyed by `(type, qualifier)`. `@as_alias(Base, qualifier=...)` makes a class
  reachable under another type, and puts it in that type's collections.
- `@as_service(lifetime="scoped" | "transient")` for a per-unit or per-call instance. A
  factory function carries the decorator too, including an async generator whose code after
  `yield` is the cleanup.
- Gate a class with `@when("prod")` / `@when_not("dev")`, never its alias — `@as_alias` is
  unconditional. `@exclude` keeps a helper out of the scan.

## Inject

```python
from collections.abc import Sequence
from typing import Annotated

from xtr_dependency_injection import Autowire, Injected, ServiceLocator, Target, as_service


@as_service
class Reporter:
    def __init__(
        self,
        mailer: Mailer,  # by type
        smtp: Annotated[Mailer, Target("smtp")],  # by qualifier
        env: Annotated[str, Autowire(param="kernel.environment")],
        port: Annotated[int, Autowire(env="int:PORT")],
        rules: Sequence[PricingRule],  # every tagged service, ordered
        handlers: ServiceLocator[Handler],  # lazy, by name
    ) -> None: ...


@on_boot
async def warm(cache: Injected[Cache]) -> None: ...
```

In a constructor or factory a bare type is enough. Everywhere a library calls *your* callable
— a hook, a console command, a message handler, a route — a container parameter must carry a
marker (`Injected[T]`, `Target(q)`, `Autowire(param=/env=)`); a bare type there is a
command-line argument or an HTTP parameter. `Target` beside `Autowire(param=/env=)` is
refused.

More, including `Sequence` / `Mapping` / `ServiceLocator`, decoration, `@remove_if_missing`
and `bind_callable`: [references/services-and-injection.md](references/services-and-injection.md).

## Configure a bundle

```python
# app/config/mail.py
from dataclasses import replace

from xtr_dependency_injection import configure, env, when
from acme_mail.bundle import MailConfig


@configure  # base: replaces the bundle's default
def mail() -> MailConfig:
    return MailConfig(host="smtp.internal")


@configure  # transform: receives the current value
@when("prod")
def mail_prod(config: MailConfig) -> MailConfig:
    return replace(config, host=env("SMTP_HOST"), port=env("SMTP_PORT", int, default=25))
```

`env()` returns a **placeholder**, never a value: the variable is read when a service needing
it is built. Parameters come from `@parameters` functions and are injected by name; a string
in a config or a parameter may hold `%other.parameter%`, and a literal percent sign is `%%`.
The whole of it: [references/configuration-and-env.md](references/configuration-and-env.md).

## Boot, shut down, and units of work

```python
from xtr_dependency_injection import Injected, on_boot, on_shutdown, unit_of_work


@on_boot(priority=100)
async def warm_cache(cache: Injected[Cache]) -> None: ...


@on_shutdown
async def flush(sink: Injected[Sink]) -> None: ...
```

Boot runs every bundle's boot, then `@on_boot` by priority; shutdown is the reverse. A failed
boot shuts down what already booted. A **sync** hook can only receive services the container
builds synchronously — anything behind an async factory (every logger, the console
application) needs `async def`.

A unit of work is one scope everything done for one message, request or command shares:

```python
async with unit_of_work(container) as unit:
    session = await unit.get(Session)  # the same instance for everything in this unit
```

`current_unit_of_work()` returns the open one, or `None`. Scoped and transient services exist
only inside a scope; `container.get()` refuses them.

## Testing

```python
from xtr_dependency_injection.testing import boot_for_test

async with await boot_for_test(kernel, overrides={Mailer: FakeMailer()}) as booted:
    greeter = await booted.container.get(Greeter)
```

- `boot_for_test(kernel, env="test", overrides=...)` builds for `test`, installs the
  overrides before any boot hook runs, and boots. A key is a type or a `(type, qualifier)` pair.
- Opt into the `booted_kernel` and `container` fixtures from `conftest.py` with
  `pytest_plugins = ["xtr_dependency_injection.testing.pytest_plugin"]`, and override the
  `xtr_kernel` fixture to return your kernel. Async tests need anyio's plugin and
  `@pytest.mark.anyio`; pytest-asyncio strict mode is unsupported.
- To swap services in a served application, `apply_overrides(compiled, overrides)` before the
  kernel is attached.

Details and the HTTP recipe: [references/testing.md](references/testing.md).

## Adding or removing an xtr package

1. Open that package's own skill, or its README section **Use in an application**, and follow
   its steps in order — install with the right extras, list the bundle in `BUNDLES` (or learn
   that another bundle already requires it), add the `@configure` module, set the variables,
   add the `.gitignore` lines.
2. Do not invent steps it does not list, and do not expect an installed package to wire
   itself.
3. Confirm with `debug:bundles`: the bundle reads `active`, and nothing you meant to activate
   is sitting under **Installed, not active**.
4. Removing is the same section read backwards, ending with `uv remove`.

## Errors

Every error derives from `DependencyInjectionError`. The ones an application meets:

| Message or error | Fix |
| --- | --- |
| `<Owner>.<param> needs <Type>, which is not a registered service` (`ContainerCompilationError`) | Mark `<Type>` `@as_service`, alias it with `@as_alias`, or check the qualifier `<Type>['q']` the message names |
| `ServiceResolutionError` saying *scope mismatch* | A scoped or transient service asked of the root container: resolve it inside `unit_of_work(container)`, from an injected parameter, or with `bind_callable(..., per_call_scope=True)` |
| `ServiceResolutionError` caused by `MissingEnvironmentVariableError` | The variable is unset; set it, or give `env()` a `default=` |
| `MissingBundleError` | A required bundle is absent, excluded or disabled for this environment |
| `UnknownConfigTypeError` | The `@configure` function returns a type no active bundle owns — list its bundle |
| `ConflictingConfigProvidersError` | Two base providers for one config. Write a transform (take the config as a parameter) instead of a second base |
| `ParameterConflictError` / `ParameterNotFoundError` | One parameter leaf set twice / `%name%` names a parameter nothing sets |
| `EnvPlaceholderError` | A placeholder used as a real value while building — typically `if env(...)` |
| `InvalidEnvironmentError` | `APP_ENV` is outside `allowed_envs` |

The full list, and what each diagnostic command prints:
[references/diagnostics-and-errors.md](references/diagnostics-and-errors.md).

## Do not

- Do not inject `ContainerInterface` to go fishing. Declare what you need: a type,
  `Sequence[T]`, `Mapping[Hashable, T]`, or `ServiceLocator[T]` for a lazy lookup by name.
- Do not import `wireup`. The engine stays behind `ContainerInterface`;
  `xtr_dependency_injection.integration.wireup` exists only for an application that builds its
  own container by hand.
- Do not put an annotation the container reads under `if TYPE_CHECKING:` — constructors,
  factories, hooks, commands, handlers, routes and config fields are read at runtime.
- Do not resolve a scoped or transient service from the root container, and do not let a
  singleton depend on one; pass it as an argument instead.
- Do not read `os.environ` while the kernel builds, and do not branch on an `env()`
  placeholder — it stands for a variable nobody has read yet.
- Do not expect an installed package to activate itself; list its bundle.
- Do not configure one bundle from another application module by hand; one `@configure`
  function per bundle, in `app/config/`.
