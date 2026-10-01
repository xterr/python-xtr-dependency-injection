# Diagnostics and errors

## The report

Every build records what it decided. `compiled.report` — and `KernelInterface.report` from
inside the container — is a `KernelReport`; `report.render()` prints plain-text tables, and
`render("bundles" | "configs" | "definitions" | "scan")` prints one section.

```
Bundles
=======
Name    Source  State   Required  Class                                                       Reason
------  ------  ------  --------  ----------------------------------------------------------  ------
kernel  kernel  active  -         xtr_dependency_injection.kernel.kernel_bundle:KernelBundle
mail    listed  active  -         acme_mail.bundle:MailBundle
```

With the console bundle active the same sections are commands:

| Command | Answers |
| --- | --- |
| `debug:bundles` | Which bundles are active and why — `listed`, `required`, skipped — and which installed ones the application left out |
| `debug:config [bundle]` | Each config's resolution steps and final value; placeholders print as `env(NAME)` |
| `debug:container [--tag TAG]` | Every definition, in emission order |

`debug:bundles` is the first thing to run after adding or removing a package. A bundle under
**Installed, not active** means the package is installed and nothing listed it.

`report.definitions` is readable from code — each entry carries `key` (a `(type, qualifier)`
pair) and `tags` — which is how a boot hook can walk tagged services in emission order.

## Reading a build failure

Two messages cover most of them.

**An unknown dependency.** The compiler names the owner, the parameter and the missing type,
and `<Type>['q']` when a qualifier was wanted:

```
app.services.Greeter.mailer needs app.services.Mailer['smtp'], which is not a registered
service: mark it @as_service (or alias it with @as_alias), or register it in a bundle's
load_extension
```

The fix is the named decorator or registration, not a stack trace from the engine — which
stays reachable as `__cause__`.

**A scope mismatch.** `container.get(T)` on a `scoped` or `transient` service says so, and
names the three ways out: an injected parameter, `bind_callable(container, target,
per_call_scope=True)`, or the container `unit_of_work(container)` yields.

## Errors

Every error derives from `DependencyInjectionError` and carries its data as typed attributes.
`ServiceNotFoundError`, `ParameterNotFoundError` and `UnknownLocatorKeyError` are also
`LookupError`s.

### Bundles and environment

| Error | Raised when |
| --- | --- |
| `DuplicateBundleError` | Two bundles share a name |
| `MissingBundleError` | A required bundle is absent, skipped, excluded or disabled |
| `CircularBundleDependencyError` | Bundle requirements loop, or an `AliasOf` forward does |
| `InvalidEnvironmentError` | The environment is not in `allowed_envs` |
| `ResourceImportError` | A scanned module failed to import |
| `BundleDefinitionError` | A malformed bundle declaration or `"module:Class"` target |

### Configuration and parameters

| Error | Raised when |
| --- | --- |
| `ConfigProviderError` | A malformed `@configure` / `@parameters`, one declared too late, or two queue markers on one object |
| `UnknownConfigTypeError` | No active bundle owns the configured type |
| `ConflictingConfigProvidersError` | Two base providers, or a base plus another bundle's forward |
| `ParameterConflictError` | One parameter leaf set twice |
| `ParameterNotFoundError` | `%name%` or `Autowire(param=...)` names nothing |
| `ParameterCircularReferenceError` / `InvalidParameterTypeError` | `%name%` references loop / a mapping embedded in a string |
| `EnvPlaceholderError` | A placeholder used as a value while building, an unknown prefix, a non-scalar embedded in a string |
| `MissingEnvironmentVariableError` / `InvalidEnvironmentVariableError` | A needed variable is unset / a processor or cast refuses its value |

### Services

| Error | Raised when |
| --- | --- |
| `DuplicateServiceError` | Two definitions claim one key |
| `UnknownServiceError` | An alias, decoration or removal targets nothing |
| `InvalidDefinitionError` | A definition contradicts itself — an unknown lifetime, an argument that does not fit, a `kernel.reset` without a usable method |
| `ServiceCircularReferenceError` | An alias chain loops |
| `DecoratorSignatureError` | A decorator without exactly one `Annotated[T, AutowireDecorated()]` parameter of the decorated type |
| `ServiceOrderError` | `@as_tagged_item` `before` / `after` contradict a priority, or cycle |
| `ContainerCompilationError` | The container could not be compiled |
| `ServiceResolutionError` | A registered service could not be built — `.reason` says why |
| `ServiceNotFoundError` | `container.get` misses |
| `UnknownLocatorKeyError` | `ServiceLocator.get` with an unknown name |
| `InvalidArgumentTypeError` / `InvalidArgumentError` | An API given the wrong kind of thing / a value it cannot use |
| `KernelAlreadyBootedError` | A compiled kernel booted twice |
| `FastapiIntegrationError` | A route resolved with no kernel attached, outside a request scope, or a second kernel attached to one application |

## Shutdown

Shutdown runs every step even when one fails, and raises the failures together as an
`ExceptionGroup` — or, when a step raised a `BaseException`, that one as it arrived, once
every step has run. A boot that fails shuts down the bundles that already booted, in reverse,
closes the container, and propagates; `@on_shutdown` hooks run only after a boot that
succeeded.

## Known limitations worth remembering

- Annotations the container reads must be importable at runtime, never under `TYPE_CHECKING`.
- `kernel.run` is asyncio only.
- Some library state is process-wide across kernels, so two kernels in one process can
  collide on a name a decorator registered at import — give such things distinct names.
- Nothing activates a bundle by discovery; advertised bundles are only reported.
