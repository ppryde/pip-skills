"""Bridge to the Node TypeScript extractor. Stub until the extractor lands (plan Task 11)."""
from __future__ import annotations

import sys

from scripts.facts import FileFacts


class DeadlineExceeded(RuntimeError):
    pass


def unavailable_reason() -> str | None:
    return "TypeScript extractor not built yet"


def extract_batch(items: list[tuple[str, str, bytes]], timeout_s: float) -> list[FileFacts]:
    raise RuntimeError("TypeScript extractor not built yet")


def setup() -> int:
    print("concordance: TypeScript extractor not built yet", file=sys.stderr)
    return 2
