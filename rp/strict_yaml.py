"""Strict YAML profile for authored metadata (problem.yaml, contribution.yaml, policy files).

Authored YAML is untrusted input. The loader composes the node graph with
PyYAML's safe parser and converts nodes itself, so no YAML constructor ever
runs. It rejects:

* duplicate mapping keys, non-string keys and merge keys (``<<``);
* explicit tags, anchors and aliases;
* more than one document, empty documents, oversized input and deep nesting;
* plain scalars that some YAML reader would silently coerce: YAML 1.1
  booleans (``yes``/``no``/``on``/``off``/``y``/``n`` in any case),
  non-canonical null spellings, floats, ``.inf``/``.nan``, octal, hex,
  binary, sexagesimal, signed or zero-padded integers, and digit separators.

Only ``true``, ``false``, ``null`` (or an empty value) and plain decimal
integers resolve to non-string values. Every other plain scalar, including
an unquoted date, stays a string; schemas check the format.

``dump`` writes YAML that this loader reads back to an equal value.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from yaml.resolver import Resolver

from rp.canonical import MAX_SAFE_INTEGER

__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_DEPTH",
    "StrictYamlError",
    "dump",
    "load",
    "load_path",
]

DEFAULT_MAX_BYTES = 256 * 1024
DEFAULT_MAX_DEPTH = 32

_STR_TAG = "tag:yaml.org,2002:str"
_TIMESTAMP_TAG = "tag:yaml.org,2002:timestamp"
_STRICT_INT = re.compile(r"-?(?:0|[1-9][0-9]*)")
_NUMBER_LIKE = re.compile(r"[-+]?(?:\.[0-9]+|[0-9][0-9_]*(?:\.[0-9_]*)?)(?:[eE][-+]?[0-9]+)?")
_SPECIAL_NUMBER = re.compile(
    r"[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN)|[-+]?0[oO][0-7_]+|[-+]?0[xX][0-9a-fA-F_]+|[-+]?0[bB][01_]+"
)
_BOOL_WORDS = {"y", "n", "yes", "no", "on", "off", "true", "false"}
_NULL_WORDS = {"~", "null"}
_RESOLVER = Resolver()


class StrictYamlError(ValueError):
    """A YAML document violates the strict profile. ``code`` is stable for tests and reports."""

    def __init__(self, code: str, message: str, line: int | None = None, column: int | None = None):
        self.code = code
        self.line = line
        self.column = column
        where = f" (line {line}, column {column})" if line is not None else ""
        super().__init__(f"{code}: {message}{where}")


def _error(code: str, message: str, mark: Any = None) -> StrictYamlError:
    if mark is None:
        return StrictYamlError(code, message)
    return StrictYamlError(code, message, mark.line + 1, mark.column + 1)


def _resolve_plain(text: str, implicit_tag: str, mark: Any = None) -> Any:
    """Resolve a plain (unquoted) scalar under the strict profile."""
    if text == "" or text == "null":
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    if _STRICT_INT.fullmatch(text):
        value = int(text)
        if abs(value) > MAX_SAFE_INTEGER:
            raise _error("yaml.ambiguous_scalar", f"integer {text} is too large; quote it", mark)
        if text == "-0":
            raise _error("yaml.ambiguous_scalar", "write 0, not -0", mark)
        return value
    lowered = text.lower()
    if lowered in _BOOL_WORDS:
        raise _error("yaml.ambiguous_scalar", f"{text!r} may be read as a boolean; quote this value", mark)
    if lowered in _NULL_WORDS:
        raise _error("yaml.ambiguous_scalar", f"{text!r} may be read as null; write null or quote it", mark)
    if text == "<<":
        raise _error("yaml.merge_key", "merge keys (<<) are not allowed", mark)
    if _NUMBER_LIKE.fullmatch(text) or _SPECIAL_NUMBER.fullmatch(text):
        raise _error(
            "yaml.ambiguous_scalar",
            f"{text!r} may be read as a number; quote this value (decimals are written as strings)",
            mark,
        )
    if implicit_tag not in (_STR_TAG, _TIMESTAMP_TAG):
        raise _error("yaml.ambiguous_scalar", f"{text!r} may be coerced by a YAML reader; quote this value", mark)
    return text


class _StrictLoader(yaml.SafeLoader):
    def __init__(self, stream: str, max_depth: int):
        super().__init__(stream)
        self._depth = 0
        self._max_depth = max_depth

    def compose_node(self, parent: Any, index: Any) -> Any:
        event = self.peek_event()
        mark = event.start_mark
        if isinstance(event, yaml.AliasEvent):
            raise _error("yaml.alias", "aliases (*name) are not allowed", mark)
        if getattr(event, "anchor", None) is not None:
            raise _error("yaml.anchor", "anchors (&name) are not allowed", mark)
        if getattr(event, "tag", None) is not None:
            raise _error("yaml.tag", f"explicit tags are not allowed (found {event.tag!r})", mark)
        self._depth += 1
        if self._depth > self._max_depth:
            raise _error("yaml.too_deep", f"nesting deeper than {self._max_depth} levels", mark)
        try:
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1


def _convert(node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        if node.style is None:
            return _resolve_plain(node.value, node.tag, node.start_mark)
        return node.value
    if isinstance(node, yaml.SequenceNode):
        return [_convert(child) for child in node.value]
    if isinstance(node, yaml.MappingNode):
        result: dict[str, Any] = {}
        for key_node, value_node in node.value:
            if not isinstance(key_node, yaml.ScalarNode):
                raise _error("yaml.non_string_key", "mapping keys must be plain strings", key_node.start_mark)
            if key_node.style is None and key_node.value == "<<":
                raise _error("yaml.merge_key", "merge keys (<<) are not allowed", key_node.start_mark)
            key = _convert(key_node)
            if not isinstance(key, str):
                raise _error("yaml.non_string_key", f"mapping key {key_node.value!r} is not a string", key_node.start_mark)
            if key in result:
                raise _error("yaml.duplicate_key", f"duplicate key {key!r}", key_node.start_mark)
            result[key] = _convert(value_node)
        return result
    raise _error("yaml.syntax", f"unsupported node {type(node).__name__}", node.start_mark)


def load(
    source: str | bytes,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> Any:
    """Parse one strict-profile YAML document and return plain Python data."""
    if isinstance(source, bytes):
        if len(source) > max_bytes:
            raise StrictYamlError("yaml.too_large", f"document exceeds {max_bytes} bytes")
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StrictYamlError("yaml.encoding", f"document is not valid UTF-8 ({exc.reason})") from exc
    else:
        text = source
        if len(text.encode("utf-8", "surrogatepass")) > max_bytes:
            raise StrictYamlError("yaml.too_large", f"document exceeds {max_bytes} bytes")
    if text.startswith("﻿"):
        text = text[1:]
    loader = _StrictLoader(text, max_depth)
    try:
        node = loader.get_single_node()
    except StrictYamlError:
        raise
    except yaml.composer.ComposerError as exc:
        code = "yaml.multiple_documents" if "single document" in str(exc) else "yaml.syntax"
        raise _error(code, str(exc).splitlines()[0], exc.problem_mark) from exc
    except yaml.MarkedYAMLError as exc:
        raise _error("yaml.syntax", f"{exc.problem or exc.context}", exc.problem_mark) from exc
    except yaml.YAMLError as exc:
        raise StrictYamlError("yaml.syntax", str(exc)) from exc
    finally:
        loader.dispose()
    if node is None:
        raise StrictYamlError("yaml.empty", "document is empty")
    return _convert(node)


def load_path(path: str | Path, **kwargs: Any) -> Any:
    return load(Path(path).read_bytes(), **kwargs)


def _plain_round_trips(text: str) -> bool:
    if text != text.strip() or text == "":
        return False
    tag = _RESOLVER.resolve(yaml.ScalarNode, text, (True, False))
    try:
        return _resolve_plain(text, tag) == text
    except StrictYamlError:
        return False


class _StrictDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    if "\n" in data:
        style = "|"
    elif _plain_round_trips(data):
        style = None
    else:
        style = '"'
    return dumper.represent_scalar(_STR_TAG, data, style=style)


def _represent_float(dumper: yaml.SafeDumper, data: float) -> yaml.ScalarNode:
    raise StrictYamlError("yaml.float", "floats are not allowed; encode decimals as strings")


_StrictDumper.add_representer(str, _represent_str)
_StrictDumper.add_representer(float, _represent_float)


def dump(data: Any) -> str:
    """Serialise ``data`` deterministically (insertion order) in the strict profile."""
    return yaml.dump(
        data,
        Dumper=_StrictDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10**9,
        indent=2,
    )
