"""Canonical JSON v1 and digests.

Canonical JSON v1 is the subset of RFC 8785 (JCS) that fingerprints need:
objects, arrays, strings, booleans, null and integers of magnitude at most
2**53 - 1. Floats are rejected (decimals are written as strings), object keys
are sorted by UTF-16 code units, separators are minimal, the output is UTF-8,
and strings are never Unicode-normalised. For this subset the output is
byte-identical to JCS, so any JCS implementation can reproduce a digest.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "CanonicalError",
    "MAX_SAFE_INTEGER",
    "canonical_json",
    "digest",
    "is_digest",
    "sha256_digest",
]

MAX_SAFE_INTEGER = 2**53 - 1
DIGEST_PREFIX = "sha256:"


class CanonicalError(ValueError):
    """Raised when a value cannot be represented in canonical JSON v1."""


def _utf16_key(key: str) -> bytes:
    return key.encode("utf-16-be", "surrogatepass")


def _check_string(value: str, path: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalError(f"{path}: string contains a lone surrogate") from exc


def _serialise(value: Any, path: str) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise CanonicalError(f"{path}: integer exceeds ±(2**53 - 1); encode it as a string")
        return str(int(value))
    if isinstance(value, float):
        raise CanonicalError(f"{path}: floats are not allowed; encode decimals as strings")
    if isinstance(value, str):
        _check_string(value, path)
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, Mapping):
        for key in value:
            if not isinstance(key, str):
                raise CanonicalError(f"{path}: object keys must be strings, got {type(key).__name__}")
            _check_string(key, f"{path}.{key!r}")
        items = sorted(value.items(), key=lambda item: _utf16_key(item[0]))
        body = ",".join(
            json.dumps(key, ensure_ascii=False) + ":" + _serialise(item, f"{path}.{key}")
            for key, item in items
        )
        return "{" + body + "}"
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return "[" + ",".join(_serialise(item, f"{path}[{i}]") for i, item in enumerate(value)) + "]"
    raise CanonicalError(f"{path}: unsupported type {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    """Return the canonical JSON v1 encoding of ``value`` as UTF-8 bytes."""
    return _serialise(value, "$").encode("utf-8")


def sha256_digest(data: bytes) -> str:
    """Return ``sha256:<hex>`` for raw bytes."""
    return DIGEST_PREFIX + hashlib.sha256(data).hexdigest()


def digest(value: Any) -> str:
    """Return ``sha256:<hex>`` of the canonical JSON encoding of ``value``."""
    return sha256_digest(canonical_json(value))


def is_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith(DIGEST_PREFIX):
        return False
    hexpart = value[len(DIGEST_PREFIX):]
    return len(hexpart) == 64 and all(c in "0123456789abcdef" for c in hexpart)
