"""The transport seam: (type, via) -> adapter factory.

Swapping how a source is reached is a config edit that selects a different
entry here — never a refactor of anything above this module.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.gather import AdapterFactory


def registry() -> dict[tuple[str, str], AdapterFactory]:
    return {}
