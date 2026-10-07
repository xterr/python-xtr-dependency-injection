"""The built-in environment variable processors: casting, decoding, reading files, defaults.

Each prefix transforms what follows it, so prefixes chain right to left:
``env("json:file:SECRETS")`` reads the variable ``SECRETS``, reads the file
it names, and decodes that as JSON. A variable the process environment does
not set, or set empty, is asked of the registered loaders, in order, each loaded once until
:meth:`EnvVarProcessor.reset`.

=================  ==========================================================
Prefix             Value
=================  ==========================================================
``string``         the raw string (the prefix when none is given)
``bool``/``not``   ``1/true/yes/on`` or a non-zero number is true; ``not`` negates
``int``            an integer: optional sign then digits, nothing else
``float``          a number; anything else is an error
``trim``           the string with surrounding whitespace removed
``base64``         decoded base64 (URL-safe characters accepted)
``urlencode``      percent-encoded
``json``           decoded JSON: an object, an array or ``null``
``csv``            a list of the comma-separated values
``url``            a dict of ``scheme``, ``host``, ``port``, ``user``, ``pass``,
                   ``path``, ``query``, ``fragment``
``query_string``   a dict of the decoded query string
``file``           the content of the file the variable names
``key:K:``         item ``K`` of the mapping (or list) what follows produces
``enum:C:``        member of enum ``C`` (``module.Class``) for the value
``const:``         the ``module.NAME`` attribute the expression names
``default:P:``     what follows, or parameter ``P`` when unset or empty
                   (``None`` when ``P`` is empty)
``defined``        whether the variable is set and not empty
``resolve``        ``%parameter%`` and ``%env(...)%`` references in the value
                   replaced by their values
``shuffle``        the list what follows produces, shuffled
=================  ==========================================================

An expression is source-controlled configuration; a value is not. So the
``%env(...)%`` references ``resolve:`` finds *inside* a value may only use
the prefixes in :data:`_VALUE_PREFIXES` — those that read the variable they
name and convert its text, and nothing else. A value cannot steer the
processor into importing a module, reading a file, reaching a parameter or
recursing.
"""

from __future__ import annotations

import base64
import binascii
import csv
import importlib
import json
import os
import random
import re
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, cast, final
from urllib.parse import parse_qs, quote, unquote, urlsplit

from typing_extensions import override

from xtr_dependency_injection.exception import (
    EnvPlaceholderError,
    InvalidEnvironmentVariableError,
    MissingEnvironmentVariableError,
)

from .env_var_processor_interface import EnvVarProcessorInterface

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .env_var_loader_interface import EnvVarLoaderInterface

__all__ = ["EnvVarProcessor"]

_PROVIDED: Final = MappingProxyType(
    {
        "base64": "string",
        "bool": "bool",
        "not": "bool",
        "const": "bool|int|float|string|array",
        "csv": "array",
        "file": "string",
        "float": "float",
        "int": "int",
        "json": "array",
        "key": "bool|int|float|string|array",
        "url": "array",
        "query_string": "array",
        "resolve": "string",
        "default": "bool|int|float|string|array",
        "string": "string",
        "trim": "string",
        "enum": "enum",
        "shuffle": "array",
        "defined": "bool",
        "urlencode": "string",
    }
)
_TRUE: Final = frozenset({"1", "true", "on", "yes"})
_NUMBER: Final = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?")
_INTEGER: Final = re.compile(r"[+-]?\d+")
_PARAMETER: Final = re.compile(r"%%|%([^%\s]+)%")
_SCALAR_PREFIXES: Final = frozenset(
    {"string", "bool", "not", "int", "float", "base64", "trim", "resolve", "urlencode"}
)
_VALUE_PREFIXES: Final = frozenset(
    {"string", "bool", "not", "int", "float", "trim", "base64", "urlencode", "defined"}
)
"""The prefixes a ``%env(...)%`` reference found inside a value may use.

Each one reads the variable it names and converts its text. None of them
imports (``const``, ``enum``), opens a file (``file``), reads a parameter
(``default``) or resolves another expression (``resolve``, ``key``,
``shuffle``) — so a value, which the process environment or a secret store
supplies, cannot decide what the processor reaches for.
"""


@final
class EnvVarProcessor(EnvVarProcessorInterface):
    """The processor behind every built-in prefix, reading the process environment and loaders.

    Resettable: :meth:`reset` forgets what the loaders provided, so the next
    lookup asks them again — a worker picks up a rotated secret between
    messages.
    """

    __slots__ = ("_environ", "_get_parameter", "_loaded", "_loaders")

    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        loaders: Iterable[EnvVarLoaderInterface] = (),
        get_parameter: Callable[[str], object] | None = None,
    ) -> None:
        """Read ``environ`` (the live process environment by default), then ``loaders``.

        Args:
            environ: Where variables are read first; ``None`` reads
                ``os.environ`` at every lookup.
            loaders: Asked, in order, for a variable ``environ`` lacks.
            get_parameter: Resolves a parameter for ``default:`` and
                ``resolve:``; without one, those prefixes cannot name one.
        """
        self._environ = environ
        self._loaders = tuple(loaders)
        self._loaded: list[Mapping[str, str]] = []
        self._get_parameter = get_parameter

    @override
    @classmethod
    def get_provided_types(cls) -> Mapping[str, str]:
        return _PROVIDED

    def reset(self) -> None:
        """Forget what the loaders provided."""
        self._loaded = []

    @override
    def get_env(self, prefix: str, name: str, get_env: Callable[[str], object]) -> object:  # noqa: PLR0911 — the prefixes reading more than the variable, one each.
        if prefix == "key":
            return self._key(name, get_env)
        if prefix == "const":
            return self._const(name)
        if prefix == "enum":
            return self._enum(name, get_env)
        if prefix == "defined":
            try:
                return get_env(name) not in (None, "")
            except MissingEnvironmentVariableError:
                return False
        if prefix == "default":
            return self._default(name, get_env)
        env = get_env(name) if ":" in name else self._raw(name)
        if prefix == "file":
            return self._file(name, env)
        if prefix == "shuffle":
            items = _as_list(name, prefix, env)
            return random.sample(items, len(items))
        if prefix in _SCALAR_PREFIXES and not isinstance(env, (str, int, float, bool)):
            raise InvalidEnvironmentVariableError(name, prefix, repr(env))
        return self._convert(prefix, name, env, get_env)

    def _convert(
        self, prefix: str, name: str, env: object, get_env: Callable[[str], object]
    ) -> object:
        text = env if isinstance(env, str) else str(env)
        if prefix in {"bool", "not"}:
            value = _boolean(env)
            return not value if prefix == "not" else value
        if prefix == "float":
            if isinstance(env, bool) or not _NUMBER.fullmatch(text.strip()):
                raise InvalidEnvironmentVariableError(name, prefix, text)
            return float(text)
        if prefix == "int":
            if isinstance(env, bool):
                raise InvalidEnvironmentVariableError(name, prefix, text)
            digits = text.strip()
            if not _INTEGER.fullmatch(digits):
                raise InvalidEnvironmentVariableError(name, prefix, text)
            return int(digits)
        if prefix == "resolve":
            return _PARAMETER.sub(lambda match: self._parameter_text(name, match, get_env), text)
        convert = _TEXT_CONVERSIONS.get(prefix)
        if convert is None:
            raise EnvPlaceholderError(f"{prefix}:{name}", f"unsupported env var prefix {prefix!r}")
        return convert(name, text)

    def _raw(self, name: str) -> str:
        """Return the variable ``name`` from the environment, else from the loaders."""
        environ = os.environ if self._environ is None else self._environ
        value = environ.get(name)
        # Truthiness, not ``is not None``: a variable set empty is asked of the
        # loaders too, and kept only when none of them has it (see the module doc).
        if value:
            return value
        for loaded in self._loaded:
            if name in loaded:
                return loaded[name]
        for loader in self._loaders[len(self._loaded) :]:
            loaded = loader.load_env_vars()
            self._loaded.append(loaded)
            if name in loaded:
                return loaded[name]
        if value is None:
            raise MissingEnvironmentVariableError(name)
        return value

    def _key(self, name: str, get_env: Callable[[str], object]) -> object:
        key, separator, rest = name.partition(":")
        if not separator:
            raise EnvPlaceholderError(
                f"key:{name}", "key: needs a key and a variable: key:KEY:NAME"
            )
        container = get_env(rest)
        if isinstance(container, Mapping):
            mapping = cast("Mapping[object, object]", container)
            if key in mapping:
                return mapping[key]
        elif isinstance(container, Sequence) and not isinstance(container, (str, bytes, bytearray)):
            items = container
            if not _INTEGER.fullmatch(key):
                # A list is read by position: a name is a mistake about the
                # shape of the value, not an item that happens to be absent.
                raise InvalidEnvironmentVariableError(rest, "key", repr(container))
            if -len(items) <= int(key) < len(items):
                return items[int(key)]
        else:
            raise InvalidEnvironmentVariableError(rest, "key", repr(container))
        raise MissingEnvironmentVariableError(f"{rest}[{key}]")

    def _const(self, name: str) -> object:
        """Return the ``module.NAME`` attribute the expression names.

        The dotted target is read from the expression itself, as ``enum:``
        reads its class — never from a variable's value, so a value cannot
        redirect which attribute is imported. ``resolve:`` keeps that true
        for the ``%env(...)%`` references it finds in a value: it refuses
        this prefix there (see :data:`_VALUE_PREFIXES`).
        """
        return _import(name, "const")

    def _enum(self, name: str, get_env: Callable[[str], object]) -> object:
        path, separator, rest = name.partition(":")
        if not separator:
            raise EnvPlaceholderError(f"enum:{name}", "enum: needs a class and a variable")
        enum = _import(path, "enum")
        if not (isinstance(enum, type) and issubclass(enum, Enum)):
            raise EnvPlaceholderError(f"enum:{name}", f"{path} is not an Enum")
        value = get_env(rest)
        try:
            return enum(value)
        except ValueError:
            # ``from None``: the enum's error quotes the value, which may be a
            # secret; the typed error keeps it in ``value``, off the message.
            raise InvalidEnvironmentVariableError(rest, enum.__qualname__, str(value)) from None

    def _default(self, name: str, get_env: Callable[[str], object]) -> object:
        fallback, separator, rest = name.partition(":")
        if not separator:
            raise EnvPlaceholderError(
                f"default:{name}", "default: needs a parameter and a variable: default:PARAM:NAME"
            )
        try:
            env = get_env(rest)
        except MissingEnvironmentVariableError:
            env = None
        if env not in (None, ""):
            return env
        if not fallback:
            return None
        return self._parameter(f"default:{name}", fallback)

    def _parameter(self, expression: str, parameter: str) -> object:
        if self._get_parameter is None:
            raise EnvPlaceholderError(expression, "parameters are not available to this processor")
        return self._get_parameter(parameter)

    def _parameter_text(
        self, name: str, match: re.Match[str], get_env: Callable[[str], object]
    ) -> str:
        if match.group(0) == "%%":
            return "%"
        reference = match.group(1)
        if reference.startswith("env(") and reference.endswith(")") and reference != "env()":
            expression = reference[4:-1]
            self._refuse_steered_expression(name, expression)
            value = get_env(expression)
        else:
            value = self._parameter(f"resolve:{name}", reference)
        if not isinstance(value, (str, int, float, bool)):
            raise InvalidEnvironmentVariableError(name, "resolve", repr(value))
        return str(value)

    def _refuse_steered_expression(self, name: str, expression: str) -> None:
        """Refuse a ``%env(...)%`` in a value that would do more than read and convert text.

        Every prefix of the chain is checked, not just the outermost: an
        allowed prefix resolves the rest of the expression through the same
        processors, so ``int:const:...`` would import just as ``const:...``
        does.

        Raises:
            EnvPlaceholderError: Naming the refused prefix. The expression
                itself comes from the value, so only the prefix is quoted.
        """
        rest = expression
        while ":" in rest:
            prefix, _, rest = rest.partition(":")
            if prefix not in _VALUE_PREFIXES:
                allowed = ", ".join(sorted(_VALUE_PREFIXES))
                reason = (
                    f"an %env(...)% reference in its value may not use the {prefix!r} prefix;"
                    f" there it is limited to {allowed}"
                )
                raise EnvPlaceholderError(f"resolve:{name}", reason)

    def _file(self, name: str, env: object) -> str:
        """Return the text of the file the variable names, read as UTF-8.

        The path comes from source-controlled configuration, not from
        untrusted input: the variable names a file the application chose to
        read, so the processor opens it directly rather than guarding against
        a path it was never meant to accept.

        A file that cannot be read, or that is not UTF-8, is refused the same
        way: a typed error naming the variable, never the operating system's
        own, whose message quotes the path.
        """
        try:
            return Path(str(env)).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # ``from None``: the underlying error quotes the path — which is
            # the variable's value, and may be a secret; the typed error keeps
            # it in ``value``, off the message.
            raise InvalidEnvironmentVariableError(name, "file", str(env)) from None


def _boolean(env: object) -> bool:
    if isinstance(env, bool):
        return env
    text = str(env).strip().lower()
    if text in _TRUE:
        return True
    return bool(_NUMBER.fullmatch(text)) and float(text) != 0


def _as_list(name: str, prefix: str, env: object) -> list[object]:
    if isinstance(env, (list, tuple)):
        return list(cast("list[object]", env))
    raise InvalidEnvironmentVariableError(name, prefix, repr(env))


def _base64(name: str, text: str) -> str:
    normalized = text.strip().translate(str.maketrans("-_", "+/"))
    padded = normalized + "=" * (-len(normalized) % 4)
    try:
        return base64.b64decode(padded, validate=True).decode()
    except binascii.Error as error:
        # The decoder's complaint is about the shape of the text, not its
        # content, so it is safe to chain and useful to read.
        raise InvalidEnvironmentVariableError(name, "base64", text) from error
    except UnicodeDecodeError:
        # ``from None``: the decoder names the byte it choked on, which is a
        # byte of the decoded value and may be part of a secret.
        raise InvalidEnvironmentVariableError(name, "base64", text) from None


def _json(name: str, text: str) -> object:
    try:
        decoded = cast("object", json.loads(text))
    except json.JSONDecodeError:
        # ``from None``: the decoder quotes the text around where it stopped,
        # which is part of the value and may be a secret. The value is elided
        # for the same reason — a document decodes as a whole or not at all,
        # so keeping it would put the entire secret on the error.
        raise InvalidEnvironmentVariableError(name, "json", _elided(text)) from None
    if decoded is None or isinstance(decoded, (dict, list)):
        return cast("object", decoded)
    raise InvalidEnvironmentVariableError(name, "json (an object, an array or null)", _elided(text))


def _elided(text: str) -> str:
    """Return a stand-in naming ``text``'s length, never its content."""
    return f"<{len(text)} characters>"


def _url(name: str, text: str) -> dict[str, object]:
    parts = urlsplit(text)
    if not parts.scheme or not parts.hostname:
        raise InvalidEnvironmentVariableError(name, "url (scheme and host expected)", text)
    return {
        "scheme": parts.scheme,
        "host": parts.hostname,
        "port": parts.port,
        "user": unquote(parts.username) if parts.username is not None else None,
        "pass": unquote(parts.password) if parts.password is not None else None,
        "path": parts.path.removeprefix("/") or None,
        "query": parts.query or None,
        "fragment": parts.fragment or None,
    }


def _import(path: str, prefix: str) -> object:
    """Return the attribute the dotted ``path`` names, imported for ``prefix``.

    Raises:
        InvalidEnvironmentVariableError: Naming ``path`` and the prefix that
            asked for it — the expression's own words, never a value's.
    """
    module, _, attribute = path.rpartition(".")
    try:
        return cast("object", getattr(importlib.import_module(module), attribute))
    except (ImportError, AttributeError, ValueError) as error:
        raise InvalidEnvironmentVariableError(path, prefix, path) from error


def _csv(_name: str, text: str) -> list[str]:
    return next(csv.reader([text])) if text else []


def _query_string(_name: str, text: str) -> dict[str, str]:
    return {key: values[-1] for key, values in parse_qs(text, keep_blank_values=True).items()}


_TEXT_CONVERSIONS: Final[Mapping[str, Callable[[str, str], object]]] = MappingProxyType(
    {
        "string": lambda _name, text: text,
        "trim": lambda _name, text: text.strip(),
        "urlencode": lambda _name, text: quote(text, safe=""),
        "base64": _base64,
        "json": _json,
        "csv": _csv,
        "url": _url,
        "query_string": _query_string,
    }
)
"""The prefixes that only transform the variable's text, by prefix."""
