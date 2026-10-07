# Services and injection

## Registering

| Decorator | Does |
| --- | --- |
| `@as_service` | Register the class or factory under its own type |
| `@as_service(lifetime=, qualifier=)` | `"singleton"` (default), `"scoped"`, `"transient"`; a qualifier tells two registrations of one type apart |
| `@as_alias(Base, qualifier=)` | Also reachable as `Base` (optionally qualified). Repeatable |
| `@as_tagged_item(index=, priority=, before=, after=)` | Place in a collection of its type |
| `@as_decorator(T, priority=, on_invalid=)` | Take `T`'s place and wrap it |
| `@autoconfigure(tags=, lifetime=, factory=)` | Apply settings to every subclass of the decorated class |
| `@autoconfigure_tag(name, **attrs)` | The same, tagging only |
| `@when(...)` / `@when_not(...)` | Skip the object outside those environments. Repeatable, widening |
| `@exclude` | Keep the object out of the scan entirely |
| `@remove_if_missing(service=/class_=/package=)` | Drop the service when a peer is absent |
| `@compiler_pass(stage=, priority=)` | Register a class with `process(builder)` as a build step |

A factory may be a function, an async function, or a generator whose code after `yield` runs
as its scope closes:

```python
@as_service(lifetime="scoped")
async def session() -> AsyncIterator[Session]:
    opened = Session()
    try:
        yield opened
    finally:
        await opened.close()
```

Put cleanup that must survive an error in `finally`: a scope's error is thrown into the
generator at the `yield`.

Gate the class, not the alias — `@as_alias` is unconditional.

## Injection markers

| Marker | Means |
| --- | --- |
| `Injected[T]` | The service of type `T`; the same as `Annotated[T, Autowire()]` |
| `Annotated[T, Target("name")]` | The `T` registered under that qualifier |
| `Annotated[str, Autowire(param="shop.name")]` | A parameter |
| `Annotated[int, Autowire(env="int:PORT")]` | An environment variable, read when built |
| `Annotated[T, AutowireDecorated()]` | Inside a decorator: the service being wrapped |

In a constructor or a factory, a bare annotated type is already injected. A marker is
required wherever a library calls your callable with arguments of its own — a `@on_boot` or
`@on_shutdown` hook, a console command, a message handler, a route — because there a bare
type means a command-line argument or an HTTP parameter. A library decides with
`is_container_supplied(annotation)`, which is true for every marker above, also inside a
union such as `Injected[T] | None`.

`Target` beside `Autowire(param=...)` or `Autowire(env=...)` is refused: a parameter is a
service, a parameter or a variable, never two.

## Collections

Declare the collection type and receive every tagged service of `T`:

| Declared | Gives |
| --- | --- |
| `Sequence[T]` | Every one, in collection order; eager |
| `Mapping[Hashable, T]` | The same, keyed by qualifier; eager; an empty one is not injectable |
| `ServiceLocator[T]` | The same keys, lazy: each entry built on `await locator.get(name)`; empty is fine |

Order is global priority descending, ties broken by `before` / `after` constraints from
`@as_tagged_item`; a contradiction or cycle raises `ServiceOrderError`. An alias takes its
target's place, so items collected through `@as_alias(Base, qualifier=...)` come out in the
order their classes declared.

```python
@as_service
class Dispatcher:
    def __init__(self, handlers: ServiceLocator[Handler]) -> None:
        self._handlers = handlers

    async def dispatch(self, name: str, message: Message) -> None:
        handler = await self._handlers.get(name)  # built here, the first time
        await handler(message)
```

`len(locator)`, `"auth" in locator`, `locator.provided_services()` and
`async for name, service in locator` all work; an unknown name raises `UnknownLocatorKeyError`.
A locator resolves each entry in the scope its consumer lives in, so a singleton cannot take
a locator with scoped members. In a route, ask for it through a marker:
`Injected[ServiceLocator[Handler]]`.

## Decorating

```python
from typing import Annotated

from xtr_dependency_injection import AutowireDecorated, OnInvalid, as_decorator


@as_decorator(Mailer, priority=10)
class LoggingMailer(Mailer):
    def __init__(
        self,
        inner: Annotated[Mailer, AutowireDecorated()],
        logger: LoggerInterface,
    ) -> None: ...
```

The highest priority wraps the original. A decorator takes the decorated service's lifetime,
lives only under the target's key, and the original drops out of every `Sequence[Mailer]`.
When the target is missing: `OnInvalid.EXCEPTION` (default) fails the build,
`OnInvalid.IGNORE` drops the decorator, `OnInvalid.NULL` keeps it with `None` for the
`AutowireDecorated` parameter — whose annotation must then allow `None`.

Exactly one `Annotated[T, AutowireDecorated()]` parameter, of the decorated type, or
`DecoratorSignatureError`.

## Overriding a bundle's service

Define the same key in the application and it wins, silently, recorded in the report. Two
bundles claiming one key is a `DuplicateServiceError`.

## Optional peers

```python
@remove_if_missing(service=MetricsCollector)
@as_service
class MetricsMiddleware: ...


@remove_if_missing(class_="acme_metrics.transports:Prometheus")
@as_service
class PrometheusExporter: ...
```

`service=`, `class_=` and `package=` are independent conditions; any non-empty combination
may be given in one call, the decorator is repeatable, and every condition must hold for the
service to survive. `class_` carries the underscore because `class` is a keyword.

## Reaching the container directly

```python
from xtr_service_contracts import ContainerInterface


async def use(container: ContainerInterface) -> None:
    mailer = await container.get(Mailer)
    special = await container.get(Mailer, "smtp")
    if container.has(MetricsCollector):
        ...
    name = container.get_parameter("kernel.name")
```

Prefer declaring what you need. Reach for the container only in code that genuinely cannot —
a diagnostic, a dynamic lookup a `ServiceLocator` cannot express.

`await optional_service(container, T, qualifier)` returns the service or `None`.

## Calling your own callables

```python
from xtr_dependency_injection import bind_callable

bound = bind_callable(container, my_handler)
result = await bound(message)
```

Returns an async function that calls the target with its marked parameters filled; a class
target is resolved on first call, and what it needs is checked at bind time. A call made
inside an open unit of work joins it; `per_call_scope=True` gives the call a scope of its own.

## Units of work

```python
from xtr_dependency_injection import current_unit_of_work, unit_of_work

async with unit_of_work(container) as unit:
    session = await unit.get(Session)  # one per unit, released when the unit ends
    await bound_handler(message)  # the same Session
```

- `unit_of_work(container)` joins the unit that container already has open; `join=False`
  opens a nested one for new work. A unit another container opened is never joined.
- `current_unit_of_work()` returns the open unit's container, or `None`.
- A library opens a unit around one piece of work — the message bus does it per message, the
  HTTP lifecycle per request.

A service that opens units injects `ScopeFactoryInterface` instead of the whole container — it
gets just that one power. `scopes.unit_of_work(join=...)` is `unit_of_work(container, join=...)`
bound to the container it was built for. The kernel registers `ScopeFactory` (from
`xtr_dependency_injection.runtime`) under the interface; a test builds one by hand with
`ScopeFactory(container)`, and a service always injects the interface.

```python
from xtr_dependency_injection import ScopeFactoryInterface, as_service


@as_service
class Worker:
    def __init__(self, scopes: ScopeFactoryInterface) -> None:
        self._scopes = scopes

    async def run(self, message: object) -> None:
        async with self._scopes.unit_of_work(join=False) as unit:
            session = await unit.get(Session)
            ...
```

## Resetting between messages

A service inheriting `ResetInterface` (from `xtr_service_contracts`) is reset by
`ServicesResetter`:

```python
@as_service
class Catalog(ResetInterface):
    def reset(self) -> None: ...


resetter = await container.get(ServicesResetter)
await resetter.reset()
```

Only services that were actually built are tracked, and weakly — a scoped or transient
resettable class with `__slots__` must list `"__weakref__"`.
