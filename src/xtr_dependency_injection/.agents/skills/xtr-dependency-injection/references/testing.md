# Testing an application on the kernel

## Boot a kernel in a test

```python
from xtr_dependency_injection.testing import boot_for_test


async def test_it_greets() -> None:
    async with await boot_for_test(kernel, overrides={Mailer: FakeMailer()}) as booted:
        greeter = await booted.container.get(Greeter)

        assert greeter.mailer.send("hi") == "fake:hi"
```

- `boot_for_test(kernel, *, env="test", overrides=...)` builds for the `test` environment,
  installs the overrides **before any boot hook runs**, and boots.
- An override key is a type, or a `(type, qualifier)` pair.
- Leaving the `async with` shuts the kernel down; so does `await booted.shutdown()`.
- `booted.container` is a `ContainerInterface`; `booted.kernel.report` is the build report.

## The fixtures

Opt in once, in `conftest.py`, and hand them your kernel:

```python
pytest_plugins = ["xtr_dependency_injection.testing.pytest_plugin"]


@pytest.fixture
def xtr_kernel() -> Kernel:
    return kernel
```

| Fixture | Is |
| --- | --- |
| `xtr_kernel` | Your kernel. Fails until you override it |
| `booted_kernel` | A kernel booted for `test`, shut down after the test |
| `container` | `booted_kernel.container` |

```python
@pytest.mark.anyio
async def test_the_catalog_is_wired(container: ContainerInterface) -> None:
    assert await container.get(BookCatalogInterface)
```

The plugin needs anyio's pytest plugin and `@pytest.mark.anyio` on async tests; strict-mode
pytest-asyncio is unsupported. An `anyio_backend` fixture returning `"asyncio"` belongs in
`conftest.py`.

## Scoped services in a test

`container.get()` refuses a scoped or transient service. Open a unit:

```python
async with unit_of_work(booted.container) as unit:
    session = await unit.get(Session)
```

Leaving the block runs the cleanup after a generator factory's `yield`, which is usually the
behaviour the test is about.

## A served application

Override before the kernel is attached, so every boot hook and every route sees the fakes:

```python
import httpx
from xtr_dependency_injection.integration.fastapi import attach
from xtr_dependency_injection.testing import apply_overrides

compiled = kernel.with_env("test").build()
apply_overrides(compiled, {Mailer: FakeMailer()})
attach(app, compiled)

transport = httpx.ASGITransport(app)
async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
    response = await client.get("/invoices/1")
```

An application that normally calls `xtr_http_kernel.setup(app, kernel)` attaches its kernel
in the lifespan; the recipe above replaces that for a test, so do not do both.

## Per-environment behaviour

`kernel.with_env("prod")` returns a kernel recipe for another environment, which is how a
test checks that `@when("prod")` services, configs and bundles land where they should.
`Kernel(environ={...})` gives one kernel its own view of the environment variables, so a test
need not touch `os.environ`.

## Checking a bundle you wrote

`assert_zero_config(BundleClass)` builds, boots and shuts down a kernel of that bundle alone,
with its default config and nothing scanned. Every bundle's suite calls it — see the
`xtr-dependency-injection-bundle-authoring` skill.
