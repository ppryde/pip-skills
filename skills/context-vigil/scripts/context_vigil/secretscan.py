"""Key-shaped strings: what context-vigil refuses to store and the dev harness masks.

One list, used everywhere a piece of text could carry a credential into a handover,
a waiting notice or a transcript. A match is only ever reported by location (a file
name, a line number), never echoed: the point is to keep the value out of output.
"""
from __future__ import annotations

import re
from typing import Optional

# Unambiguous token formats, plus upper-case KEY/TOKEN/SECRET/PASSWORD assignments and
# a few lower-case compound names (``api_key: …``) whose value is long enough to be real.
_SHAPES = (
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{8,}",               # Anthropic / OpenAI style keys
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",                     # AWS access key ids
    r"\bgh[pousr]_[A-Za-z0-9]{20,}",                      # GitHub tokens
    r"\bgithub_pat_[A-Za-z0-9_]{20,}",
    r"\bxox[abprs]-[A-Za-z0-9-]{10,}",                    # Slack tokens
    r"\bAIza[0-9A-Za-z_-]{30,}",                          # Google API keys
    r"\bglpat-[A-Za-z0-9_-]{20,}",                        # GitLab tokens
    r"\bnpm_[A-Za-z0-9]{30,}",                            # npm tokens
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY( BLOCK)?-----",    # PEM / PGP private keys
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.",       # JWTs
    r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@",         # credentials in a URL
    r"\b[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)[A-Z0-9_]*\s*[=:]\s*\S+",
    r"(?i:\b(?:password|passwd|api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token"
    r"|client[_-]?secret|private[_-]?key)[\"']?\s*[=:]\s*[\"']?[^\s\"']{6,})",
    r"(?i:\bauthorization\s*:\s*(?:bearer|basic|token)\s+\S+)",
)
KEY_SHAPE = re.compile("|".join(f"(?:{s})" for s in _SHAPES))


def looks_secret(text: str) -> bool:
    return KEY_SHAPE.search(text) is not None


def first_secret_line(text: str) -> Optional[int]:
    """1-based number of the first line holding something key-shaped, else None."""
    for number, line in enumerate(text.splitlines(), 1):
        if KEY_SHAPE.search(line):
            return number
    return None


def redact(text: str, mask: str = "[redacted]") -> str:
    return KEY_SHAPE.sub(mask, text)
