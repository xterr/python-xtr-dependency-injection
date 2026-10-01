# Compiler passes and PassStage

A compiler pass is one method: `process(builder)`, satisfying `CompilerPassInterface`. A bundle
reaches them two ways.

**Override `process`.** The bundle is then itself a pass, running in `BEFORE_OPTIMIZATION` at
priority -10000, in bundle order, after every built-in pass of that stage. Use it for the
whole-container view: collect tagged services, hand them to a definition, rewrite a provider.

**Register a pass object from `build`**, for anything needing another stage or priority:

```python
from xtr_dependency_injection import ContainerBuilder, PassStage


class DropUnusedSpoolers:
    def process(self, builder: ContainerBuilder) -> None:
        for key in builder.find_tagged_service_ids("mail.spooler"):
            if not builder.has(SpoolerInterface, key[1]):
                builder.remove_definition(*key)
                builder.log(self, f"dropped {key[0].__qualname__}")

    @override
    def build(self, builder: ContainerBuilder) -> None:
        builder.add_compiler_pass(
            DropUnusedSpoolers(), stage=PassStage.BEFORE_REMOVING, priority=10
        )
```

`add_compiler_pass` is allowed only from `build`; anywhere else it raises `BuilderPhaseError`.
A pass that does not implement `CompilerPassInterface` is a `TypeError`.

## Order

The merge pass runs first: every `prepend_extension`, the configs (their `%name%` references
resolved), every `load_extension`, the late scans from `services.load(...)`, and the
application's marked definitions. Then the five stages, in order:

| Stage | For |
| --- | --- |
| `BEFORE_OPTIMIZATION` | Seeing and shaping definitions; autoconfiguration happens here |
| `OPTIMIZE` | Resolving references, placeholders, decorations, validity |
| `BEFORE_REMOVING` | Last look before anything goes |
| `REMOVE` | Dropping and forwarding |
| `AFTER_REMOVING` | After the container's shape is final |

Within a stage: priority descending, then registration order. That means built-in passes first,
then bundle passes in bundle order, then the application's `@compiler_pass` classes in scan
order.

## The built-in passes

| Stage | Priority | Pass | Does |
| --- | --- | --- | --- |
| `BEFORE_OPTIMIZATION` | 100 | `RegisterAutoconfigureAttributesPass` | Turns `@autoconfigure` / `@autoconfigure_tag` markers into rules |
| | 100 | `AutowireAsDecoratorPass` | Turns scanned `@as_decorator` classes into decorating definitions |
| | 100 | `AttributeAutoconfigurationPass` | Runs `register_attribute_for_autoconfiguration` callbacks |
| | 100 | `ResolveInstanceofConditionalsPass` | Applies the autoconfiguration rules |
| | 100 | `RegisterEnvVarProcessorsPass` | Registers the environment variable processors and loaders |
| | 100 | `RemoveMissingDependenciesPass` | Drops `@remove_if_missing` services whose peer is absent |
| | -32 | `ResettableServicePass` | Checks every `kernel.reset` tag names a real method |
| | -10000 | Every bundle overriding `process` | Bundle order |
| `OPTIMIZE` | 0 | `ResolveParameterPlaceHoldersPass` | Resolves `%name%` in parameters and definition arguments |
| | 0 | `ValidateEnvPlaceholdersPass` | Refuses an unknown prefix, or a non-scalar placeholder inside a string |
| | 0 | `DecoratorServicePass` | Resolves decorations by priority, applies `on_invalid` |
| | 0 | `CheckDefinitionValidityPass` | Checks kind, provider, key, lifetime and arguments agree |
| | 0 | `ResolveReferencesToAliasesPass` | Points alias chains at their definition, refuses loops |
| `BEFORE_REMOVING` | 0 | `CheckAliasValidityPass` | Checks an alias target class implements the alias |
| `REMOVE` | 0 | `ReplaceAliasByActualDefinitionPass` | Gives every alias a forwarding definition |

So a pass that must see autoconfiguration's output runs below priority 100 in
`BEFORE_OPTIMIZATION`, or later; one that must run before placeholders resolve stays in
`BEFORE_OPTIMIZATION`.

## Logging what a pass decided

`builder.log(self, message)` records a line under the pass, and
`builder.get_compiler().get_log()` reads them back. Log a removal, an override or a fallback:
it is the only trace left of a decision the container's shape no longer shows.

## Collecting in `process`

```python
    @override
    def process(self, builder: ContainerBuilder) -> None:
        receivers: dict[str, ServiceKey] = {}
        for key, tags in builder.find_tagged_service_ids(RECEIVER_TAG).items():
            for attributes in tags:
                alias = attributes.get("alias")
                if not isinstance(alias, str) or not alias:
                    raise MessageBusError(f"receiver {key[0].__qualname__} is tagged with no alias")
                receivers[alias] = key
        _ = builder.get_definition(WorkerFactory).set_argument("receiver_keys", receivers)
```

Set the argument to an empty default in `load_extension` first, so the definition is valid even
when nothing is tagged. The engine cannot resolve an empty collection, so where a definition
injects a `Sequence[T]` of tagged services, keep a variant that takes none and swap the
provider in `process` only once at least one exists.
