# Lifecycle, user callables and helpers

## Where a bundle's hooks sit

```
build()     environment → bundles → early scan → build() of every bundle →
            configs (default → app base → AliasOf → prepends → app transforms) →
            load_extension → late scan → the application's definitions →
            compiler passes by stage → compile
boot()      bundle.boot() in bundle order → the application's @on_boot hooks
shutdown()  @on_shutdown hooks → bundle.shutdown() in reverse → container.close()
```

Required bundles boot before their requirer and shut down after it, so a peer's services are
there throughout your `boot`.

A boot that fails shuts down the bundles that already booted, in reverse, and closes the
container; the application's `@on_shutdown` hooks run only after a boot that succeeded. A
`BaseException`, `KeyboardInterrupt` included, triggers the same rollback and propagates.
Shutdown runs every step even when one fails, and raises the failures together as an
`ExceptionGroup`.

So `shutdown` must tolerate a `boot` that never finished: keep what it has to release on the
instance, and check it.

```python
    @override
    async def shutdown(self) -> None:
        restore = self._restore
        if restore is not None:
            self._restore = None
            restore()
```

Hold a restore callable rather than an open `async with` block: shutdown may be awaited in
another task than boot was.

A generator factory registered with `services.set` has its cleanup run as the container closes.
Put cleanup that must survive an error in `finally`, because the engine throws a scope's error
into the generator.

## Calling the user's callables

A library that calls something the application wrote, a handler, a command, a listener, binds it
through the container:

```python
from xtr_dependency_injection import bind_callable

bound = bind_callable(container, handler)
result = await bound(message)
```

`bind_callable(container, target, *, per_call_scope=False, signature=None)` returns a coroutine
function. The target is a function, or a class registered with the container whose instances are
called, resolved lazily on the first call. What it needs is checked at bind time, which is why a
bundle binds in `boot`: a handler asking for something the container cannot provide fails at
startup, not on its first message. `signature=` presents a different signature, with annotations
already evaluated.

Tell the parameters you pass yourself from the ones the container fills:

```python
from xtr_dependency_injection import is_container_supplied

for name, parameter in inspect.signature(handler).parameters.items():
    if is_container_supplied(parameter.annotation):
        continue  # the container fills this one
```

`is_container_supplied` is true for `Injected[T]`, `Annotated[T, Autowire(...)]`,
`Annotated[T, Target(...)]`, a bare `ServiceLocator[T]`, and each of those inside a union such
as `Injected[T] | None`. Ask it rather than looking for one marker, so every library agrees on
what a marker is, including markers added later.

A bare `T` is never injected. Say so in the library's documentation: a user's handler must
annotate every container dependency.

## Units of work

A unit of work is one scope everything done for one message, job or request shares. A
`lifetime="scoped"` service, a database session, is built once per unit, seen by everything in
it, and released when the unit ends, even when it raised.

```python
from xtr_dependency_injection import unit_of_work

async with unit_of_work(container, join=False) as unit:
    session = await unit.get(Session)
    await bound_handler(message)  # the same Session
```

A library opens one around each piece of work it runs: `join=True` (the default) joins the unit
that container already has open, so work started inside a unit shares its instances;
`join=False` opens one of its own, which is what a worker does per message it received.
`current_unit_of_work()` returns the open unit's container, or `None` outside one, for a service
that needs "the one for this unit".

A `bind_callable` target bound without `per_call_scope` joins whatever unit is open where the
call is made. `per_call_scope=True` keeps a scope of its own, and that scope is the unit of
whatever the call starts.

## Resetting between pieces of work

A library that runs many pieces of work in one process clears stateful services between them:

```python
resetter = await container.get(ServicesResetter)
await resetter.reset()
```

Anything inheriting `ResetInterface` (from `xtr-service-contracts`) is autoconfigured into that;
a bundle opts a service in explicitly with
`services.set(X).add_tag("kernel.reset", method="clear")`. The `method` is required and must
exist, or the build fails. Only services that were actually built are tracked, weakly, so a
`scoped` or `transient` resettable class with `__slots__` must list `"__weakref__"`.

## Small helpers

| Helper | For |
| --- | --- |
| `bundle_active(builder, name)` | Whether bundle `name` is active in this build, from `build` onwards. It reads `kernel.bundles`, so earlier it answers `False` |
| `await optional_service(container, T, qualifier)` | The service, or `None` when the container does not provide it |
| `named_factory(factory, name)` | Renames a factory function, so the report and its errors say `mail_spooler_bulk` rather than `spooler` for each |
| `one_or_many(value)` | A config field written as one entry or several, as a tuple |
| `qualified_name(obj)` | `module:QualName`, for a tag attribute or an error message |
| `Reference(service, qualifier)` | A config value pointing at a service the container provides |

`named_factory` renames the function itself, so give it one made for that name: a closure per
configured name.

```python
def _spooler_for(name: str) -> Callable[[ContainerInterface], Awaitable[Spooler]]:
    async def spooler(container: ContainerInterface) -> Spooler:
        logger = await optional_service(container, LoggerInterface, "mail")
        return Spooler(name, logger)

    return named_factory(spooler, f"mail_spooler_{name}")


_ = services.set(_spooler_for(name), qualifier=name)
```

A factory is registered under its annotated return type, so annotate it, and qualify every
registration of one type.

## What a service may ask for

Register services that declare their dependencies, and nothing wider:

| Parameter | Gets |
| --- | --- |
| `dep: Dependency` | The service registered under that type |
| `Annotated[T, Target("smtp")]` | The qualified one |
| `Annotated[str, Autowire(param="kernel.name")]` | A parameter |
| `Annotated[int, Autowire(env="int:PORT")]` | An environment variable |
| `Sequence[T]` / `Mapping[Hashable, T]` | Every tagged service of `T`, eagerly |
| `ServiceLocator[T]` | The same, lazily, built per name on `await locator.get(name)` |

`ServiceLocator[T]` is the one to reach for where a configuration names a handful of many
registered services: nothing is built until it is asked for. A type nothing registers yields an
empty locator, where an empty `Mapping[Hashable, T]` is simply not injectable.

A service taking `ContainerInterface` is the last resort, for a factory that must resolve by a
name only the config knows. Never take it to avoid declaring a dependency.
