# Config, parameters and placeholders

## How a config resolves

A bundle's config is built once per kernel build, in one order, and every step is recorded in the
report (`debug:config`):

1. the bundle's default, `MailConfig()`;
2. the application's base `@configure` provider, one taking no argument and returning the type.
   A provider under `@when` / `@when_not` wins over an unconditional one;
3. an `AliasOf` forward from another bundle, at most one per config;
4. other bundles' prepends, in bundle order, so they add to what the application chose;
5. the application's transforms, those taking the current value: unconditional first, then
   conditional, by `priority`, then scan order.

Two base providers in one group, or an application base against a forward, is a
`ConflictingConfigProvidersError` naming both.

Consequences for a bundle:

- Treat the config as data an application already changed. Never read a field in `build`, which
  runs before resolution.
- From `load_extension` onwards, `builder.get_extension_config(bundle)` reads a peer's resolved
  config, by name or by type.
- `prepend_extension_config` must *add*, not replace: a transform discarding the application's
  value will surprise whoever wrote it.

## AliasOf: forwarding a config key

A bundle whose config has a field `Annotated[C | None, AliasOf("target")]` forwards that field's
non-`None` value to bundle `target`. The owner's config resolves before its target's, whatever
the bundle order; a loop is a `CircularBundleDependencyError`.

```python
from typing import Annotated

from xtr_dependency_injection import AliasOf


@dataclass(frozen=True, slots=True)
class MailConfig:
    host: str = "localhost"
    logging: Annotated[LoggingConfig | None, AliasOf("logging")] = None
```

Use it for a family where one facade config is the single place an application writes. The
annotation must be importable at runtime, not hidden under `TYPE_CHECKING`, or the forward would
be silently dropped (it raises `NameError` instead).

## Parameters

A bundle adds parameters from `build`:

```python
        builder.set_parameter("mail.spool_dir", "%kernel.share_dir%/mail")
```

They merge into nested mappings and never override: a leaf set twice is a
`ParameterConflictError` naming both sources. The kernel provides `kernel.name`,
`kernel.environment`, `kernel.debug`, `kernel.project_dir`, `kernel.share_dir` and
`kernel.bundles`.

`kernel.share_dir` is `var/share` in the project directory, owned by whoever owns the project.
Write there for anything the application's processes share on one machine, never into the
system's temporary directory. Create nothing until something actually writes.

A service reads a parameter with `Annotated[str, Autowire(param="mail.spool_dir")]`; the bundle
reads one while building with `builder.get_parameter(name)`. A string anywhere in a config or a
parameter may reference another between percent signs:

| Written | Becomes |
| --- | --- |
| `"%kernel.project_dir%"` | the parameter's own value, whatever its type |
| `"%kernel.project_dir%/var/log"` | the value embedded; only a string or a number can be |
| `"100%%"` | `100%` |
| `"%env(int:PORT)%"` | the placeholder `env("int:PORT")` |

Unknown name: `ParameterNotFoundError`. A loop: `ParameterCircularReferenceError`. A mapping
embedded in a string: `InvalidParameterTypeError`.

## Environment variables in a config

`env()` returns a **placeholder**, never a value. The variable is read when a service needing it
is built, so the container compiles without the environment it will run in, and no report prints
a secret.

What this means for a bundle:

- A config field may hold a placeholder. Validation in `__post_init__` sees the `default=`, else
  `0` or the token, so guard numeric and membership checks with `isinstance`.
- Never branch on a placeholder while building. Testing one in an `if` raises
  `EnvPlaceholderError`.
- Pass it on with `set_argument`, or read it from a config a factory takes as a parameter, and
  it resolves where it lands. A factory reaching a placeholder through anything else, another
  function, or the bundle object itself, fails the build with an `InvalidDefinitionError`
  pointing at `set_argument`.
- In `boot`, `await container.get(MailConfig)` gives a resolved copy, validated again. That is
  where a missing variable should fail the application, not on its first use.

A library may add prefixes by registering a service implementing `EnvVarProcessorInterface`
(`get_env(prefix, name, get_env)`, `get_provided_types()`), or supply variables the environment
lacks with `EnvVarLoaderInterface` (`load_env_vars() -> Mapping[str, str]`). Both are
autoconfigured.

## Reference: pointing a config at a service

Where a config field would otherwise name something the bundle builds itself, let the
application point at a service it already owns:

```python
from xtr_dependency_injection import Reference

LockConfig(resources={"default": Reference(Redis, "locks")})
```

`Reference(service, qualifier=None)` is a frozen dataclass with three members a bundle uses:

| Call | For |
| --- | --- |
| `reference.exists_in(container)` | Checking it in `boot`, so a reference to nothing fails at startup |
| `await reference.resolve(container)` | Fetching it when the service needing it is built |
| `str(reference)` | Naming it in an error: `Redis['locks']` |

The application keeps the lifecycle of what it referenced; the bundle closes only what it opened
itself.

## one_or_many

A config field an application may write as one entry or several, read as a tuple either way. A
list or a tuple is several; anything else, a string included, is one.

```python
from xtr_dependency_injection import one_or_many

for entry in one_or_many(entries):
    ...
```
