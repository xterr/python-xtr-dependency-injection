"""Placeholders standing for environment variables until the service needing one is built.

``env(...)`` returns a placeholder, never a value: the variable is read when
a service that needs it is built, through the container's environment
variable processors. The build only carries the placeholder around, so a
container compiles without the environment it will run in, a service nobody
builds never reads its variables, and no report ever prints a secret.

A placeholder is an instance of the type it stands for where Python allows
it — an ``int``, ``float`` or ``str`` — so a config's own validation still
runs while the kernel builds, against the ``default`` when one is given
(``0``, or the token for a string, otherwise). ``bool`` and ``Enum`` cannot
be subclassed; a placeholder for one is an opaque object. Every placeholder
renders as a unique token, so ``f"https://{env('HOST')}/api"`` keeps its
placeholder inside the string, and the token is replaced when the string is
resolved. Testing a placeholder in an ``if`` raises: a variable read later
cannot decide what the container contains now.

Resolution walks a value — a placeholder, a string holding tokens, a mapping,
a sequence, a dataclass, a msgspec ``Struct`` or a pydantic model — and
rebuilds only what holds a placeholder.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Mapping
from enum import Enum
from typing import TYPE_CHECKING, Final, final

from typing_extensions import override

from xtr_dependency_injection.exception import (
    EnvPlaceholderError,
    InvalidEnvironmentVariableError,
    MissingEnvironmentVariableError,
)
from xtr_dependency_injection.exception._naming import qualified_name

from ._walk import leaves, rebuild

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

__all__ = [
    "ENV_PARAMETERS_ROOT",
    "MISSING",
    "EnvPlaceholder",
    "Missing",
    "env_parameter",
    "env_placeholders_embedded_in",
    "env_placeholders_in",
    "env_tokens",
    "placeholder",
    "resolve_env_placeholders",
]

ENV_PARAMETERS_ROOT: Final = "__xtr_env__"
"""The parameter every ``Autowire(env=...)`` injection is read from, one key per token."""

_STRING_PREFIXES: Final = frozenset(
    {"", "string", "trim", "file", "base64", "resolve", "urlencode"}
)
_SCALARS: Final = (str, int, float, bool)
_NOT_A_STRUCTURE: Final = (
    "an environment variable is read when the service needing it is built, "
    "so it cannot decide what the container contains"
)


class Missing(Enum):
    """The type of :data:`MISSING`: no default was given."""

    MISSING = "MISSING"


MISSING: Final = Missing.MISSING


class EnvPlaceholder:
    """What ``env(...)`` returns: an environment variable not read yet.

    Attributes:
        expression: What the processors resolve, e.g. ``"int:PORT"`` or
            ``"json:file:SECRETS"``.
        cast: Applied to the processed value when the placeholder was asked
            for with a callable no processor prefix stands for; ``None``
            otherwise.
        default: Returned when the variable is not set; :data:`MISSING`
            makes a missing variable an error.
        token: The unique string the placeholder renders as.
    """

    expression: str = ""
    cast: Callable[..., object] | None = None
    default: object = MISSING
    token: str = ""

    def resolve(self, get_env: Callable[[str], object]) -> object:
        """Return the value ``get_env`` reads for this placeholder, cast and defaulted.

        Raises:
            MissingEnvironmentVariableError: If the variable is not set and
                no default was given.
            InvalidEnvironmentVariableError: If the cast refuses the value.
        """
        try:
            value = get_env(self.expression)
        except MissingEnvironmentVariableError:
            if self.default is MISSING:
                raise
            return self.default
        if self.cast is None:
            return value
        try:
            return self.cast(value)
        except (TypeError, ValueError) as error:
            raise InvalidEnvironmentVariableError(self.expression, self.cast, str(value)) from error

    def __bool__(self) -> bool:
        """Refuse: a placeholder has no truth value until it is resolved.

        Raises:
            EnvPlaceholderError: Always.
        """
        raise EnvPlaceholderError(self.expression, _NOT_A_STRUCTURE)

    @override
    def __repr__(self) -> str:
        return f"env({self.expression})"

    @override
    def __str__(self) -> str:
        return self.token

    @override
    def __format__(self, format_spec: str) -> str:
        return self.token

    @override
    def __reduce__(self) -> tuple[object, ...]:
        return (placeholder, (self.expression, self.cast, self.default))


@final
class _StrPlaceholder(EnvPlaceholder, str):
    """A placeholder for a string: its content is the default, else its token.

    ``str()`` and f-strings render the token either way, so an embedded
    placeholder is still found; string methods see the content, so a
    config validating a string sees the default while the kernel builds.
    """

    __slots__ = ()


@final
class _IntPlaceholder(EnvPlaceholder, int):
    """A placeholder for an ``int``: its value is the default, for validation while building."""

    __slots__ = ()


@final
class _FloatPlaceholder(EnvPlaceholder, float):
    """A placeholder for a ``float``: its value is the default, for validation while building."""

    __slots__ = ()


@final
class _OpaquePlaceholder(EnvPlaceholder):
    """A placeholder for a type that cannot be subclassed, or is not known yet."""


_REGISTRY: dict[str, EnvPlaceholder] = {}
"""Every placeholder made in this process, by token — the same spec always gets one token."""

_BY_DIGEST: dict[str, EnvPlaceholder] = {}
"""The same placeholders, by the digest ending their token."""

_SALT: Final = secrets.token_bytes(16)
"""Keys the token digests, so no string can name a placeholder it was not handed."""

_TOKEN: Final = re.compile(r"env_\w*?_([0-9a-f]{32})(?![0-9a-f])")
"""What a token looks like: ``env_<expression>_<digest>``. The digest ends it."""


def placeholder(
    expression: str,
    cast: Callable[..., object] | None = None,
    default: object = MISSING,
) -> EnvPlaceholder:
    """Return the placeholder for ``expression``, made once per spec.

    The placeholder's runtime type follows the outermost processor prefix:
    ``int:`` makes an ``int``, ``float:`` a ``float``, no prefix or a string
    prefix a ``str``; anything else, or a ``cast`` no prefix stands for, an
    opaque placeholder.
    """
    digest = hashlib.blake2b(
        f"{expression}|{qualified_name(cast)}|{default!r}".encode(), key=_SALT, digest_size=16
    ).hexdigest()
    token = f"env_{re.sub(r'[^A-Za-z0-9_]', '_', expression)}_{digest}"
    existing = _REGISTRY.get(token)
    if existing is not None:
        return existing
    made = _make(expression, cast, default, token)
    made.expression, made.cast, made.default, made.token = expression, cast, default, token
    _REGISTRY[token] = made
    _BY_DIGEST[digest] = made
    return made


def _make(
    expression: str, cast: Callable[..., object] | None, default: object, token: str
) -> EnvPlaceholder:
    prefix = expression.partition(":")[0] if ":" in expression else ""
    if cast is not None:
        return _OpaquePlaceholder()
    if prefix == "int":
        return _IntPlaceholder(default if isinstance(default, int) else 0)
    if prefix == "float":
        return _FloatPlaceholder(default if isinstance(default, (int, float)) else 0.0)
    if prefix in _STRING_PREFIXES:
        return _StrPlaceholder(default if isinstance(default, str) else token)
    return _OpaquePlaceholder()


def env_parameter(expression: str) -> str:
    """Return the dotted parameter an ``Autowire(env=expression)`` injection reads."""
    return f"{ENV_PARAMETERS_ROOT}.{placeholder(expression).token}"


@final
class _EnvTokens(Mapping[str, EnvPlaceholder]):
    """Every placeholder by token, live — the engine's view of :data:`ENV_PARAMETERS_ROOT`."""

    __slots__ = ()

    @override
    def __getitem__(self, token: str) -> EnvPlaceholder:
        return _REGISTRY[token]

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(tuple(_REGISTRY))

    @override
    def __len__(self) -> int:
        return len(_REGISTRY)


_TOKENS: Final = _EnvTokens()


def env_tokens() -> Mapping[str, EnvPlaceholder]:
    """Return every placeholder by token, including those made after this call."""
    return _TOKENS


def env_placeholders_in(value: object) -> list[EnvPlaceholder]:
    """Return every placeholder ``value`` holds, once each, in the order they are found."""
    found: dict[str, EnvPlaceholder] = {}
    for leaf in leaves(value):
        if isinstance(leaf, EnvPlaceholder):
            _ = found.setdefault(leaf.token, leaf)
        elif isinstance(leaf, str):
            for held, _span in _tokens_in(leaf):
                _ = found.setdefault(held.token, held)
    return list(found.values())


def env_placeholders_embedded_in(value: object) -> list[EnvPlaceholder]:
    """Return every placeholder ``value`` holds inside a longer string, once each."""
    found: dict[str, EnvPlaceholder] = {}
    for leaf in leaves(value):
        if isinstance(leaf, str) and not isinstance(leaf, EnvPlaceholder):
            for held, _span in _tokens_in(leaf):
                if held.token != leaf:
                    _ = found.setdefault(held.token, held)
    return list(found.values())


def _tokens_in(text: str) -> Iterator[tuple[EnvPlaceholder, tuple[int, int]]]:
    """Yield every placeholder whose token ``text`` holds, with where the token is.

    A candidate ends at its digest; the token it names is a suffix of what
    matched, so text running into a token (``env_a_env_B_<digest>``) still
    finds it.
    """
    if "env_" not in text:
        return
    for match in _TOKEN.finditer(text):
        held = _BY_DIGEST.get(match.group(1))
        if held is not None and match.group(0).endswith(held.token):
            yield held, (match.end() - len(held.token), match.end())


def resolve_env_placeholders(value: object, get_env: Callable[[str], object]) -> object:
    """Return ``value`` with every placeholder replaced by what ``get_env`` reads.

    Only what holds a placeholder is rebuilt (see
    :func:`~xtr_dependency_injection.config._walk.rebuild`), so a dataclass's
    validation runs again against the real values.

    Raises:
        EnvPlaceholderError: If a token embedded in a string resolves to
            something other than a string, number or bool.
        MissingEnvironmentVariableError: If a variable is not set and has no
            default.
        InvalidEnvironmentVariableError: If a processor or cast refuses a
            value.
    """
    resolved: dict[str, object] = {}

    def value_of(held: EnvPlaceholder) -> object:
        if held.token not in resolved:
            resolved[held.token] = held.resolve(get_env)
        return resolved[held.token]

    def leaf(value: object) -> object:
        if isinstance(value, EnvPlaceholder):
            return value_of(value)
        if isinstance(value, str):
            return _resolve_string(value, value_of)
        return value

    return rebuild(value, leaf)


def _resolve_string(value: str, value_of: Callable[[EnvPlaceholder], object]) -> object:
    """Return ``value`` with its tokens replaced — in one pass, so a value is never rescanned."""
    whole = _REGISTRY.get(value)
    if whole is not None:  # a placeholder that lost its type on the way — ``str(placeholder)``
        return value_of(whole)
    parts: list[str] = []
    position = 0
    for held, (start, end) in _tokens_in(value):
        replacement = value_of(held)
        if not isinstance(replacement, _SCALARS):
            reason = (
                f"resolves to {type(replacement).__qualname__}, which cannot be embedded "
                "in a string: only strings, numbers and bools can"
            )
            raise EnvPlaceholderError(held.expression, reason)
        parts.extend((value[position:start], str(replacement)))
        position = end
    if not parts:
        return value
    parts.append(value[position:])
    return "".join(parts)
