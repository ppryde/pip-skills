"""Key-shaped strings: what context-vigil refuses to store and the dev harness masks.

One list, used everywhere a piece of text could carry a credential into a handover,
a waiting notice or a transcript. A match is only ever reported by location (a file
name, a line number), never echoed: the point is to keep the value out of output.

High confidence only. Handover notes talk ABOUT credentials all the time ("GITHUB_TOKEN:
missing in CI", ``API_KEY=<redacted>``, ``$TOKEN``, commit SHAs, digests), and a false
refusal lands while the session sits above its threshold. So a match is either a
known token format (a vendor prefix with enough characters behind it, a PEM private
key header, a JWT, a password in a URL) or an assignment to a credential NAME whose
value is a long literal holding letters and digits, never a placeholder or a
variable reference. Accepted residual risk: a bare 40-hex token with no name beside
it reads as a commit SHA, and a letters-only or very short password is not caught.
"""
from __future__ import annotations

import re
from typing import Optional

# A credential-looking literal: starts like a key (not ``$``, ``<``, ``{``, ``*``,
# ``/``, ``~``, ``.``, a quote or a bracket), holds a letter and a digit, and ends at
# whitespace, a quote, a delimiter or the end of the line — so ``os.environ['X']``,
# ``${X}`` and ``<your token>`` never qualify.
_END = r"(?=$|[\s\"'`,;)\]}>])"
_LITERAL = (r"(?=[A-Za-z0-9+/_.=~-]*[0-9])(?=[A-Za-z0-9+/_.=~-]*[A-Za-z])"
            r"[A-Za-z0-9+_-][A-Za-z0-9+/_.=~-]{15,}" + _END)
# Passwords are shorter and carry punctuation: 8+ characters, a letter and a digit.
_PASSWORD = (r"(?=[^\s\"'`<>]*[0-9])(?=[^\s\"'`<>]*[A-Za-z])"
             r"[A-Za-z0-9+_!@#%^&-][^\s\"'`<>]{7,}" + _END)

# A credential NAME as a whole token: ``API_KEY``, ``db-password``, ``apiKey``,
# ``SECRET_KEY_BASE`` — never ``MONKEY``/``HOTKEY``/``KEYERROR`` (no separator before
# the keyword) and never ``TOKEN_PATH``/``KEY_ID``/``TOKEN_TTL`` (a trailing part that
# says the value is not the credential itself).
_NOT_THE_VALUE = (r"(?!(?i:path|file|filename|dir|url|uri|name|ttl|id|len|length|count"
                  r"|settings|helper|env|type|prefix|header|var|field|expiry|expires|timeout"
                  r"|size|limit|cmd|command|source|ref)(?![A-Za-z0-9]))")
_LEAD = r"(?<![A-Za-z0-9])(?:[A-Za-z0-9]+[_.-]|[A-Za-z][a-z0-9]+(?=[A-Z]))*"
_TAIL = r"(?:[_-]" + _NOT_THE_VALUE + r"[A-Za-z0-9]+)*"
_KEY_WORDS = r"(?i:api_?key|key|token|secret|credentials?)"
_PASS_WORDS = r"(?i:password|passwd|passphrase|pwd|pass)"
_SEP = r"[\"']?\s*(?:=|:=|:|=>)\s*[\"']?"

_SHAPES = (
    r"(?<![A-Za-z0-9])sk-(?=[A-Za-z0-9_-]*[A-Z0-9])[A-Za-z0-9_-]{8,}",   # Anthropic / OpenAI
    r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}",                       # Stripe
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",                                # AWS access key ids
    r"\bgh[pousr]_[A-Za-z0-9]{20,}",                                 # GitHub tokens
    r"\bgithub_pat_[A-Za-z0-9_]{20,}",
    r"\bxox[abprs]-[A-Za-z0-9-]{10,}",                               # Slack tokens
    r"https://hooks\.slack\.com/services/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9]{16,}",
    r"\bAIza[0-9A-Za-z_-]{30,}",                                     # Google API keys
    r"\bya29\.[A-Za-z0-9_-]{20,}",                                   # Google OAuth
    r"\bglpat-[A-Za-z0-9_-]{20,}",                                   # GitLab tokens
    r"\bnpm_[A-Za-z0-9]{30,}",                                       # npm tokens
    r"\bhf_[A-Za-z0-9]{30,}",                                        # Hugging Face
    r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}",                 # SendGrid
    r"\bdo[por]_v1_[a-f0-9]{64}",                                    # DigitalOcean
    r"AGE-SECRET-KEY-1[0-9A-Z]{50,}",                                # age
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY( BLOCK)?-----",               # PEM / PGP private keys
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.",                  # JWTs
    # a password in a URL: not a placeholder, 6+ characters with a digit
    r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:(?![$<{*%])(?=[^/\s@]*[0-9])[^/\s@]{6,}@",
    _LEAD + _KEY_WORDS + _TAIL + _SEP + _LITERAL,                    # API_KEY=<literal>
    _LEAD + _PASS_WORDS + _TAIL + _SEP + _PASSWORD,                  # DB_PASSWORD=<literal>
    r"(?<![A-Za-z0-9-])--(?i:api-key|token|secret|password)[ =]" + _LITERAL,
    r"(?i:\bauthorization\s*:\s*(?:bearer|basic|token)\s+)" + _LITERAL,
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
