"""Opaque identifiers: a type prefix plus a random 128-bit UUID version 4.

Identifiers never depend on model, filename, date, discipline, repository or
display order (§3), which is why UUIDv7 (time-ordered) is not used. The UUID
is written as 32 lowercase hex digits without hyphens, e.g.
``prb_3f2a9c0e8b7d4e1fa6c5b4d3e2f1a0b9``. See docs/adr/0002.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
import uuid
from dataclasses import dataclass
from typing import Protocol

__all__ = [
    "KIND_PREFIXES",
    "IdSource",
    "InvalidIdentifier",
    "ParsedId",
    "SeededIdSource",
    "SystemIdSource",
    "id_kind",
    "id_pattern",
    "is_id",
    "new_id",
    "parse_id",
]

KIND_PREFIXES = {
    "problem": "prb",
    "contribution": "con",
    "revision": "rev",
    "statement_revision": "stm",
    "artifact": "art",
    "event": "evt",
    "publication_snapshot": "pub",
    "person": "per",
}
PREFIX_KINDS = {prefix: kind for kind, prefix in KIND_PREFIXES.items()}

# Version nibble 4 at hex position 12; RFC 4122 variant (8, 9, a, b) at position 16.
_UUID4_HEX = r"[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}"
_ID_RE = re.compile(rf"({'|'.join(PREFIX_KINDS)})_({_UUID4_HEX})")


class InvalidIdentifier(ValueError):
    pass


def id_pattern(kind: str) -> str:
    """Anchored regular expression for identifiers of ``kind`` (shared with the JSON Schemas)."""
    return rf"^{KIND_PREFIXES[kind]}_{_UUID4_HEX}$"


class IdSource(Protocol):
    def random_bytes(self) -> bytes:
        """Return 16 bytes."""
        ...


class SystemIdSource:
    def random_bytes(self) -> bytes:
        return secrets.token_bytes(16)


class SeededIdSource:
    """Deterministic source for fixtures and tests. Never use it for production identifiers."""

    def __init__(self, seed: str):
        self._seed = seed.encode("utf-8")
        self._counter = 0
        self._lock = threading.Lock()

    def random_bytes(self) -> bytes:
        with self._lock:
            n = self._counter
            self._counter += 1
        return hashlib.sha256(self._seed + b"\x00" + n.to_bytes(8, "big")).digest()[:16]


_SYSTEM_SOURCE = SystemIdSource()


def new_id(kind: str, source: IdSource | None = None) -> str:
    if kind not in KIND_PREFIXES:
        raise InvalidIdentifier(f"unknown identifier kind {kind!r}")
    raw = bytearray((source or _SYSTEM_SOURCE).random_bytes())
    if len(raw) != 16:
        raise InvalidIdentifier("an identifier source must return 16 bytes")
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return f"{KIND_PREFIXES[kind]}_{raw.hex()}"


@dataclass(frozen=True, slots=True)
class ParsedId:
    kind: str
    uuid: uuid.UUID

    @property
    def hex(self) -> str:
        return self.uuid.hex


def parse_id(value: object, kind: str | None = None) -> ParsedId:
    match = _ID_RE.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise InvalidIdentifier(f"{value!r} is not a valid identifier")
    parsed = ParsedId(PREFIX_KINDS[match.group(1)], uuid.UUID(hex=match.group(2)))
    if kind is not None and parsed.kind != kind:
        raise InvalidIdentifier(f"{value!r} is a {parsed.kind} identifier, expected {kind}")
    return parsed


def is_id(value: object, kind: str | None = None) -> bool:
    try:
        parse_id(value, kind)
    except InvalidIdentifier:
        return False
    return True


def id_kind(value: object) -> str:
    return parse_id(value).kind
