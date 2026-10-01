# Configuration, parameters and environment variables

Everything an application writes under `app/config/`.

## `@configure`

A bundle's config type is a frozen dataclass buildable with no arguments; it validates itself
in `__post_init__`. The application provides or transforms it, and the two are told apart by
the signature:

```python
@configure  # base: takes nothing, replaces the default
def mail() -> MailConfig:
    return MailConfig(host="smtp.internal")


@configure(priority=10)  # transform: takes the current value
def mail_spool(config: MailConfig) -> MailConfig:
    return replace(config, spool="%kernel.project_dir%/var/spool")
```

Resolution order, recorded step by step in `debug:config`:

1. the bundle's default, `MailConfig()`;
2. the application's base provider — one under `@when` / `@when_not` beats an unconditional one;
3. a forward from another bundle's config field (`AliasOf`), at most one;
4. other bundles' prepends, in bundle order;
5. the application's transforms — unconditional first, then conditional; by `priority`, then
   scan order.

Rules:

- One base provider per config. A second is a `ConflictingConfigProvidersError`; write a
  transform instead.
- A config another bundle forwards to with `AliasOf` takes **no** application base provider —
  transform it.
- Returning a type no active bundle owns is an `UnknownConfigTypeError`.
- Put `@configure`, `@parameters` and `@compiler_pass` in modules the early scan sees, never
  in a module a bundle loads late.

## Parameters

Named values injected by key. The kernel provides `kernel.name`, `kernel.environment`,
`kernel.debug`, `kernel.project_dir`, `kernel.share_dir` and `kernel.bundles`; bundles add
theirs; the application adds its own:

```python
from xtr_dependency_injection import env, parameters


@parameters
def shop_parameters() -> dict[str, object]:
    return {
        "shop": {
            "name": env("SHOP_NAME"),
            "page_size": "%env(int:SHOP_PAGE_SIZE)%",
            "var_dir": "%kernel.project_dir%/var",
            "log_dir": "%shop.var_dir%/log",
            "motto": "100%% independent",
        },
    }
```

```python
@as_service
class Site:
    def __init__(self, name: Annotated[str, Autowire(param="shop.name")]) -> None: ...
```

- A key never contains a dot; nesting is what makes `shop.var_dir` a path.
- Parameters merge and never override: a leaf set twice is a `ParameterConflictError` naming
  both sources.
- `kernel.share_dir` (`var/share` under the project) is where one application's processes
  share files. Keep `var/` out of version control.
- At runtime a service reads the compiled parameters by injecting `ContainerBagInterface`.

### `%name%` references

Any string in a bundle config or a parameter may hold one:

| Written | Becomes |
| --- | --- |
| `"%kernel.project_dir%"` | the parameter's own value, whatever its type |
| `"%kernel.project_dir%/var/log"` | the value embedded — only a string or a number may be |
| `"100%%"` | `100%` |
| `"%env(int:PORT)%"` | the placeholder `env("int:PORT")` |

An unknown name is a `ParameterNotFoundError`, a loop a `ParameterCircularReferenceError`, a
mapping embedded in a string an `InvalidParameterTypeError`.

## `env()`

`env()` never reads a value. It returns a placeholder, and the variable is read when a
service that needs it is built — so the container compiles without the environment it will
run in, a service nobody builds never reads its variables, and no report prints a secret
(`debug:config` shows `env(SMTP_PASSWORD)`).

```python
config = replace(
    config,
    host=env("SMTP_HOST"),
    port=env("SMTP_PORT", int, default=25),
    dsn=f"smtp://{env('SMTP_HOST')}:{env('SMTP_PORT', int)}",
    options=env("json:file:SMTP_OPTIONS_FILE"),
)
```

- `env("PORT", int)` — `int`, `float`, `bool`, `str` and an `Enum` class become the matching
  processor prefix; any other callable is applied to the processed value.
- `env("json:file:SECRETS")` — a processor chain, read right to left.
- `default=` is returned when the variable is unset, and is what a numeric placeholder stands
  for while the kernel builds, so the config's own validation still sees something plausible.
- `Annotated[int, Autowire(env="int:PORT")]` injects one straight into a parameter.

### Processor prefixes

| Prefix | Value |
| --- | --- |
| *(none)* / `string` | the raw string |
| `bool` / `not` | `1/true/yes/on` or a non-zero number is true; `not` negates |
| `int` / `float` | a number; anything else is an error |
| `trim` / `urlencode` / `base64` | stripped / percent-encoded / decoded |
| `json` / `csv` | an object, array or null / a list |
| `url` / `query_string` | a dict of the URL's parts / of the query |
| `file` | the content of the file the variable names |
| `key:K:` / `enum:C:` / `const:` | item `K` / a member of enum `C` / the named constant |
| `default:P:` | what follows, or parameter `P` when unset or empty |
| `defined` / `resolve` / `shuffle` | set and not empty / `%param%` and `%env(X)%` replaced / shuffled list |

### Where the values come from

The process environment first — or `Kernel(environ={...})`, which gives one kernel its own —
then every loader: a service implementing `EnvVarLoaderInterface`
(`load_env_vars() -> Mapping[str, str]`) is asked for what the environment lacks. A service
implementing `EnvVarProcessorInterface` (`get_env(prefix, name, get_env)`,
`get_provided_types()`) adds prefixes or replaces built-in ones.

Load `.env` files into the environment with xtr-dotenv **at the entry point**, before the
kernel is built.

### What a placeholder cannot do

- It cannot decide what the container contains: `if env("FEATURE"):` while the kernel builds
  raises `EnvPlaceholderError`.
- A missing variable fails the service that needs it, on first build, as a
  `ServiceResolutionError` caused by `MissingEnvironmentVariableError`.
- Placeholders are process-wide: one per distinct `env()` expression, read through each
  kernel's own processors.
