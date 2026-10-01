# Autoconfiguration

The kernel scans the application package and every active bundle's `resources`, sorted by name,
skipping `*.tests`, `*.test_*`, `*.conftest` and `*.__main__`, and considering only what a
module *defines*. Everything that is not already claimed by a queue marker becomes a **service
candidate**, and candidates are what a bundle's autoconfigurators see.

A bundle has two ways to claim them. Both are registered from `build`.

## By base type

```python
    @override
    def build(self, builder: ContainerBuilder) -> None:
        _ = builder.register_for_autoconfiguration(ResetInterface).add_tag(
            "kernel.reset",
            method="reset",
        )
```

`register_for_autoconfiguration(type_)` returns an `AutoconfigureRule` matching every definition
whose built type has `type_` in its `__mro__`, a nominal subclass check, never a structural one.
`add_tag(name, **attributes)` returns the rule, so calls chain. A rule also carries `lifetime`
and `factory`, so it can set a lifetime or turn a matched class definition into a factory
definition.

`ResolveInstanceofConditionalsPass` applies the rules at `BEFORE_OPTIMIZATION` priority 100, to
every non-kernel definition. A tag already on a definition wins over the rule's: explicit stays.

Pick this when the library already has an interface the application inherits.

## By a marker the library defines

```python
    @override
    def build(self, builder: ContainerBuilder) -> None:
        builder.register_attribute_for_autoconfiguration(handlers_declared_on, register_handler)
```

`register_attribute_for_autoconfiguration(reader, callback)` takes two callables:

- `reader(obj)` returns the metadata items found on a candidate, one per registration to make,
  and an empty iterable for a candidate it does not recognise. It is where the library's own
  decorator (`@as_message_handler(IngestDocument)`) is read back off the class.
- `callback(obj, item, services)` is called once per item, with this bundle's
  `ServiceConfigurator`, so it registers, tags and aliases exactly as `load_extension` would.

```python
        def register_handler(obj: object, message_type: type, services: ServiceConfigurator) -> None:
            if isinstance(obj, type):
                _ = services.set(obj).add_tag("mail.handler", handles=qualified_name(message_type))
```

`AttributeAutoconfigurationPass` runs the callbacks at `BEFORE_OPTIMIZATION` priority 100.
Guard `isinstance(obj, type)`: a candidate may be a function, and a function usually needs
binding rather than registering.

Pick this when the library's own declaration already says what a class is for, so the
application needs no second decorator.

## What the application does instead

Applications reach the same effect on their own classes, and a library should document these
rather than ask for a wrapper of its own:

```python
from xtr_dependency_injection import as_service, autoconfigure, autoconfigure_tag


@autoconfigure(tags=[("mail.spooler", {"priority": 10})])
class Spooler: ...


@autoconfigure_tag("mail.strategy")
class Strategy: ...  # every subclass tagged
```

So a library that only needs tagged services should publish its tag name as a public constant
and read it with `builder.find_tagged_service_ids(TAG)`:

```python
RECEIVER_TAG: Final = "messenger.receiver"
```

## Scanning only when a peer is active

`resources=` on `@as_bundle` is scanned whenever the bundle is active. For a module that should
only be scanned when a peer is there, scan it late from `load_extension`:

```python
        if bundle_active(builder, "console"):
            services.load("acme_mail.command")
```

A late scan runs after every bundle loaded, so it may not declare `@configure`, `@parameters` or
`@compiler_pass`: each of those is needed before bundles load. Put them in `resources`.

## Tag ordering

Where the order of collected services matters, the application controls it with
`@as_tagged_item(index=, priority=, before=, after=)`: collection order is global priority
descending, with `before` / `after` breaking ties. A contradiction, an unsatisfiable bound or a
cycle is a `ServiceOrderError`. A library collecting a `Sequence[T]` therefore gets a
deterministic order without doing anything itself.
