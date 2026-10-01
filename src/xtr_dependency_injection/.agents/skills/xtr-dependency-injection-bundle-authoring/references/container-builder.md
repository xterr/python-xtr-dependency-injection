# The ContainerBuilder and Definition surface

Every hook receives a `ContainerBuilder` bound to this bundle's origin, so whatever it writes
is recorded as this bundle's. One method, one purpose.

## Definitions

| Method | Does |
| --- | --- |
| `register(service, *, qualifier=, lifetime=)` | Register a new definition and return it |
| `set_definition(definition)` | Store a fully built `Definition` |
| `get_definition(service, qualifier=)` | Fetch a definition by key |
| `has_definition(service, qualifier=)` | Test whether a definition exists |
| `find_definition(service, qualifier=)` | Resolve aliases, return the underlying definition |
| `remove_definition(service, qualifier=)` | Drop a definition |
| `get_definitions()` | Every definition, as a tuple |
| `has(service, qualifier=)` | A definition or an alias is present |
| `find_tagged_service_ids(tag)` | `{ServiceKey: [attribute mappings]}` for every definition carrying `tag` |

A `ServiceKey` is `(type, qualifier)`. Every service id is a type; the optional qualifier tells
two registrations of one type apart.

## Aliases

| Method | Does |
| --- | --- |
| `set_alias(alias, target, *, alias_qualifier=, target_qualifier=)` | Point one key at another |
| `get_alias(alias, qualifier=)` / `get_aliases()` | Read one / all |
| `has_alias(alias, qualifier=)` / `remove_alias(alias, qualifier=)` | Test / drop |

In `load_extension` prefer `services.alias(...)`, which is the same thing with this bundle's
origin attached. An alias whose target class does not implement the alias fails the build; a
missing target is an `UnknownServiceError`; a loop is a `ServiceCircularReferenceError`.

An alias takes its target's place in a collection, so tagged items reached through aliases come
out of `Sequence[Base]` in the order their classes were given.

## Parameters and the compiler

| Method | Does |
| --- | --- |
| `get_parameter(name)` / `has_parameter(name)` / `set_parameter(name, value)` | Read / test / write a parameter (dotted name) |
| `get_parameter_bag()` | The parameters as an `EnvPlaceholderParameterBag` while building |
| `add_compiler_pass(pass, *, stage=, priority=)` | Register a pass, only from `build` |
| `get_compiler()` / `log(pass, message)` | The compiler and its log / add a line to it |
| `get_extension_config(bundle)` | Read another bundle's resolved config, by name or by type |
| `prepend_extension_config(bundle, transform)` | Transform another bundle's config, only from `prepend_extension` |

Read a parameter from the builder rather than from the container when a service needs it at
definition time: a container compiled without the kernel's parameters still gets the value.

```python
lock_dir = str(Path(str(builder.get_parameter("kernel.share_dir"))) / "lock")
_ = services.set(store_factory, qualifier=resource).set_arguments(
    {"stores": stores, "lock_dir": lock_dir},
)
```

## A Definition

Mutable, and carrying: `key`, `provider`, `kind` (`"class"` / `"factory"` / `"instance"`),
`lifetime`, `origin`, `tags`, `decorates`, `priority`, `before`, `after`, `arguments`.

| Method | Does |
| --- | --- |
| `add_tag(name, **attributes)` | Tag it; attributes are what a collector reads |
| `has_tag(name)` / `get_tag(name)` / `clear_tag(name)` | Test / read / drop a tag |
| `set_argument(name, value)` / `set_arguments(mapping)` / `get_arguments()` | Give the provider a value by parameter name |
| `set_decorated_service(target, *, qualifier=, priority=, on_invalid=)` | Make it decorate another service |

An argument is passed to the provider instead of being injected. It must name a parameter the
provider takes by keyword (or the provider takes `**kwargs`); an instance takes none, and a
decorator's argument cannot be its decorated service. `CheckDefinitionValidityPass` fails the
build otherwise, and `ResolveParameterPlaceHoldersPass` resolves `%name%` references in
arguments first.

## Decoration from a bundle

```python
_ = services.set(LoggingMailer).set_decorated_service(Mailer)
```

The decorator takes the target's key and its lifetime, receives the original through a
parameter annotated `Annotated[Mailer, AutowireDecorated()]`, and keeps the original out of
every `Sequence[Mailer]`. Decorations of one service apply by `priority`, highest wrapping
outermost.

`on_invalid` decides what a missing target means: `OnInvalid.EXCEPTION` (the default) fails the
build, `OnInvalid.IGNORE` drops the decorator, `OnInvalid.NULL` keeps it and passes `None`, so
the annotation must allow `None`. A decorator without exactly one `AutowireDecorated` parameter
of the decorated type is a `DecoratorSignatureError`.

## Dropping a service when a peer is absent

```python
from xtr_dependency_injection import as_service, remove_if_missing


@remove_if_missing(service=MetricsCollector)
@remove_if_missing(package="acme-metrics")
@as_service
class MetricsMiddleware: ...
```

`service=` (optionally with `qualifier=`), `class_="module:Class"` and `package="dist-name"`
are each an independent condition; any non-empty combination may be given in one call, an empty
call is a `TypeError`, and the decorator repeats. `RemoveMissingDependenciesPass`
(`BEFORE_OPTIMIZATION`, priority 100) drops the definition when any condition fails, together
with every alias of it; a decorator of it then follows its own `on_invalid`. The trailing
underscore on `class_` avoids the keyword, and there is no parent-package condition.

## Two bundles, one key

Two bundles defining one key is a `DuplicateServiceError`. The later bundle takes it over by
calling `builder.set_definition(...)` from `process`, which is also where it can rewrite
another bundle's definition:

```python
    @override
    def process(self, builder: ContainerBuilder) -> None:
        builder.get_definition(TransportFactory).provider = combined_transport_factory_with
```

An application overriding a bundle's service by defining the same key is allowed silently, and
recorded in the report.
