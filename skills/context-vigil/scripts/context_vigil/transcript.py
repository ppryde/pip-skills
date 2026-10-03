"""Incremental, tail-only transcript reading: cost is O(new bytes), never O(file).

First read walks backwards from EOF in 64 KB chunks until a usage record turns
up; later reads seek to the stored offset and read forward to EOF. A partial
trailing line is left for next time (unless it already parses), a file shorter
than the stored offset was truncated or rotated so reading restarts from the
tail, and invalid UTF-8 is replaced per line, never raised.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional, Tuple

CHUNK = 64 * 1024
MAX_FORWARD = 8 * 1024 * 1024   # a bigger gap than this is read from the tail instead
_MODEL_LOOKAHEAD_CHUNKS = 4     # past the usage record, look this far for an identity record
_USAGE_FIELDS = (
    "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")

_ENTRYPOINTS = {"sdk-cli": True, "cli": False, "claude-desktop": False}


@dataclass
class Tail:
    has_usage: bool = False           # a record carrying message.usage was seen
    tokens: Optional[int] = None      # its input + cache totals; None when unreadable
    model_id: Optional[str] = None    # latest attachment.identity.modelId
    message_model: Optional[str] = None  # latest message.model
    offset: int = 0                   # where the next read should start
    bytes_read: int = 0


def _parse(line: bytes) -> Optional[Dict[str, Any]]:
    try:
        record = json.loads(line.decode("utf-8", errors="replace"))
    except (ValueError, RecursionError):
        return None
    return record if isinstance(record, dict) else None


def _tokens(usage: Dict[str, Any]) -> Optional[int]:
    try:
        return sum(int(usage.get(field, 0) or 0) for field in _USAGE_FIELDS)
    except (TypeError, ValueError, OverflowError):
        return None


def _identity_model(record: Dict[str, Any]) -> Optional[str]:
    # undocumented internal record: any other shape falls through quietly
    attachment = record.get("attachment")
    identity = attachment.get("identity") if isinstance(attachment, dict) else None
    model = identity.get("modelId") if isinstance(identity, dict) else None
    return model if isinstance(model, str) and model else None


def _message_model(message: Any) -> Optional[str]:
    model = message.get("model") if isinstance(message, dict) else None
    return model if isinstance(model, str) and model and not model.startswith("<") else None


def _reverse_lines(f: Any, size: int, tail: Tail) -> Iterator[bytes]:
    """Lines from EOF backwards; the first item is whatever follows the last newline."""
    pos = size
    carry = b""
    while pos > 0:
        start = max(0, pos - CHUNK)
        f.seek(start)
        data = f.read(pos - start)
        tail.bytes_read += len(data)
        pos = start
        parts = (data + carry).split(b"\n")
        carry = parts[0]
        for part in reversed(parts[1:]):
            yield part
    yield carry


def _scan_back(f: Any, size: int) -> Tail:
    tail = Tail(offset=size)
    extra_chunks = float(_MODEL_LOOKAHEAD_CHUNKS)
    for index, line in enumerate(_reverse_lines(f, size, tail)):
        if index == 0 and line:
            if _parse(line) is None:   # a half-written final record: read it next time
                tail.offset = size - len(line)
                continue
        record = _parse(line) if line else None
        if record is None:
            continue
        if tail.model_id is None:
            tail.model_id = _identity_model(record)
        message = record.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if not tail.has_usage and isinstance(usage, dict):
            tail.has_usage = True
            tail.tokens = _tokens(usage)
            tail.message_model = _message_model(message)
        elif tail.has_usage:
            extra_chunks -= len(line) / CHUNK
        if tail.has_usage and (tail.model_id is not None or extra_chunks <= 0):
            break
    return tail


def _scan_forward(f: Any, offset: int) -> Tail:
    f.seek(offset)
    data = f.read()
    tail = Tail(offset=offset, bytes_read=len(data))
    cut = data.rfind(b"\n") + 1
    complete, partial = data[:cut], data[cut:]
    consumed = cut
    lines = complete.split(b"\n")
    if partial and _parse(partial) is not None:
        lines.append(partial)
        consumed = len(data)
    tail.offset = offset + consumed
    for line in lines:
        record = _parse(line) if line else None
        if record is None:
            continue
        model_id = _identity_model(record)
        if model_id is not None:
            tail.model_id = model_id
        message = record.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if isinstance(usage, dict):
            tail.has_usage = True
            tail.tokens = _tokens(usage)
        message_model = _message_model(message)
        if message_model is not None:
            tail.message_model = message_model
    return tail


def read_tail(path: str, offset: Optional[int] = None) -> Optional[Tail]:
    """New usage/model information since ``offset`` (None: first read, from the tail)."""
    try:
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if offset is None or offset > size or size - offset > MAX_FORWARD:
                return _scan_back(f, size)
            return _scan_forward(f, offset)
    except (OSError, ValueError):
        return None


def read_entrypoint(path: str) -> Tuple[bool, Optional[bool]]:
    """(head was readable, headless?) from the first records' ``entrypoint``."""
    try:
        with open(path, "rb") as f:
            head = f.read(CHUNK)
    except (OSError, ValueError):
        return False, None
    readable = False
    for line in head.split(b"\n")[:-1] if len(head) == CHUNK else head.split(b"\n"):
        record = _parse(line) if line else None
        if record is None:
            continue
        readable = True
        entrypoint = record.get("entrypoint")
        if isinstance(entrypoint, str):
            return True, _ENTRYPOINTS.get(entrypoint)
    return readable, None
