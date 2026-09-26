"""Read Anthropic's pricing page: one parser over its markdown and HTML forms.

The live page (``platform.claude.com/docs/en/about-claude/pricing.md``) is plain
markdown; the Internet Archive's older snapshots are HTML. Both reduce to the
same thing — a table of ``Model | Base input tokens | 5m cache writes | 1h cache
writes | Cache hits and refreshes | Output tokens`` — so ``extract_tables`` turns
either into rows of cell text and ``parse_pricing`` reads the first table whose
headers say it is the model-price table. Columns are found by header keyword,
not position, and a single ``Cache Writes`` column (older pages) is the
5-minute price.

Tolerance, in one rule: the page is not ours, so anything unexpected yields an
error and NO prices (``ParseResult.error``), never a half-read table. A single
row that cannot be read is skipped and reported (``skipped``), never guessed.
Nothing here writes to the store or raises out of ``parse_pricing``; fetching
raises only ``FetchError``.
"""
from __future__ import annotations

import html as htmllib
import re
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser

PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
USER_AGENT = "chronicle-pricing/1 (local list-price tracker)"
MAX_BYTES = 8_000_000


class FetchError(Exception):
    """A page could not be fetched (bad scheme, network, HTTP, size)."""


@dataclass(frozen=True)
class PagePrice:
    """USD per million tokens as the page states them. The cache-write prices
    are None when the page has no such column."""
    input: float
    output: float
    cache_read: float
    cache_write_5m: float | None
    cache_write_1h: float | None


@dataclass
class ParseResult:
    prices: dict[str, PagePrice] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    error: str | None = None


def fetch_text(url: str, *, timeout: float = 5.0, max_bytes: int = MAX_BYTES) -> str:
    """GET ``url`` as text; ``FetchError`` for anything that is not a clean
    http(s) 200 within the size cap."""
    if not url.startswith(("https://", "http://")):
        raise FetchError(f"refusing non-http(s) url: {url!r}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
    except Exception as exc:  # network, HTTP status, TLS, timeout... all one contract
        raise FetchError(f"{type(exc).__name__}: {exc}") from exc
    if len(raw) > max_bytes:
        raise FetchError(f"response larger than {max_bytes} bytes")
    return raw.decode("utf-8", errors="replace")


# -- model names ----------------------------------------------------------

_NAME_FAMILY_FIRST = re.compile(r"^claude\s+([a-z]+)\s+(\d+(?:\.\d+)*)$", re.IGNORECASE)
_NAME_VERSION_FIRST = re.compile(r"^claude\s+(\d+(?:\.\d+)*)\s+([a-z]+)$", re.IGNORECASE)


def model_id(display_name: str) -> str | None:
    """The API model id a page's display name stands for: ``Claude Opus 5.5`` ->
    ``claude-opus-5-5``. Claude 3 ids put the version first
    (``Claude Haiku 3.5`` -> ``claude-3-5-haiku``). None for anything that is
    not ``Claude <family> <version>`` (a dated snapshot id then resolves to the
    family by prefix at read time, see ``ratebook``)."""
    name = re.sub(r"\s+", " ", display_name).strip()
    m = _NAME_FAMILY_FIRST.match(name)
    if m:
        family, version = m.group(1).lower(), m.group(2)
    else:
        m = _NAME_VERSION_FIRST.match(name)
        if not m:
            return None
        version, family = m.group(1), m.group(2).lower()
    parts = version.split(".")
    if int(parts[0]) < 4:
        return f"claude-{'-'.join(parts)}-{family}"
    return f"claude-{family}-{'-'.join(parts)}"


# -- tables ---------------------------------------------------------------

_Table = list[list[str]]


def _clean(cell: str) -> str:
    cell = re.sub(r"<sup\b[^>]*>.*?</sup>", "", cell, flags=re.IGNORECASE | re.DOTALL)
    cell = re.sub(r"<[^>]+>", "", cell)
    return htmllib.unescape(cell).replace("*", "").replace("`", "").strip()


def _markdown_tables(text: str) -> list[_Table]:
    tables: list[_Table] = []
    current: _Table = []
    for line in [*text.splitlines(), ""]:
        stripped = line.strip()
        if stripped.startswith("|"):
            inner = stripped[1:-1] if stripped.endswith("|") and len(stripped) > 1 else stripped[1:]
            cells = [_clean(c) for c in re.split(r"(?<!\\)\|", inner)]
            if all(re.fullmatch(r":?-+:?", c.replace(" ", "")) for c in cells if c) and any(cells):
                continue                                    # the |---|---| separator
            current.append(cells)
        elif current:
            tables.append(current)
            current = []
    return tables


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[_Table] = []
        self._stack: list[_Table] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._hidden = 0          # inside <sup>/<script>/<style>

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._stack.append([])
        elif tag == "tr" and self._stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag in ("sup", "script", "style"):
            self._hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(_clean("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._stack:
            if self._row:
                self._stack[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._stack:
            self.tables.append(self._stack.pop())
        elif tag in ("sup", "script", "style") and self._hidden:
            self._hidden -= 1

    def handle_data(self, data: str) -> None:
        if self._cell is not None and not self._hidden:
            self._cell.append(data)


def extract_tables(text: str) -> list[_Table]:
    """Every table in ``text`` as rows of cleaned cell text — HTML ``<table>``s
    and markdown pipe tables alike, in that order."""
    tables: list[_Table] = []
    if "<table" in text.lower():
        parser = _TableParser()
        try:
            parser.feed(text)
            parser.close()
        except Exception:  # noqa: BLE001, S110 - malformed HTML must not escape; what parsed so far stands
            pass
        tables.extend(parser.tables)
    tables.extend(_markdown_tables(text))
    return [t for t in tables if t]


# -- the model-price table ------------------------------------------------

_PRICE = re.compile(r"\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)")


def _price(cell: str) -> float | None:
    m = _PRICE.search(cell)
    return float(m.group(1).replace(",", "")) if m else None


def _columns(header: list[str]) -> dict[str, int] | None:
    """Field -> column index from a header row, or None when it lacks the
    model / input / output / cache-read columns that make it THE price table."""
    cols: dict[str, int] = {}
    for i, raw in enumerate(header):
        h = raw.lower()
        if "model" in h and "model" not in cols:
            cols["model"] = i
        elif "output" in h:
            cols.setdefault("output", i)
        elif "input" in h and "cache" not in h:
            cols.setdefault("input", i)
        elif "5m" in h or "5 min" in h:
            cols.setdefault("cache_write_5m", i)
        elif "1h" in h or "1 hour" in h:
            cols.setdefault("cache_write_1h", i)
        elif "cache" in h and "write" in h:
            cols.setdefault("cache_write_5m", i)
        elif "hit" in h or "read" in h or "refresh" in h:
            cols.setdefault("cache_read", i)
    return cols if {"model", "input", "output", "cache_read"} <= set(cols) else None


def _model_cell(cell: str) -> str:
    return re.split(r"[(\[]", cell, maxsplit=1)[0].strip()


def parse_pricing(text: str) -> ParseResult:
    """The model-price table of a pricing page (markdown or HTML) as
    ``{model id: PagePrice}``. Never raises; ``error`` set means ``prices`` is
    empty and nothing should be recorded."""
    tables = extract_tables(text or "")
    if not tables:
        return ParseResult(error="no tables found in the page")
    for table in tables:
        cols = _columns(table[0])
        if cols is None:
            continue
        return _read_table(table[1:], cols)
    return ParseResult(error="no table has the Model / input / output / cache-read columns")


def _read_table(rows: _Table, cols: dict[str, int]) -> ParseResult:
    result = ParseResult()
    width = max(cols.values()) + 1
    for row in rows:
        name = _model_cell(row[cols["model"]]) if len(row) > cols["model"] else ""
        if len(row) < width:
            result.skipped.append(f"{name or row!r}: row too short")
            continue
        model = model_id(name)
        if model is None:
            result.skipped.append(f"{name!r}: not a Claude model name")
            continue
        nums = {f: _price(row[i]) for f, i in cols.items() if f != "model"}
        inp, out, read = nums["input"], nums["output"], nums["cache_read"]
        if inp is None or out is None or read is None or min(inp, out, read) <= 0:
            result.skipped.append(f"{name}: unreadable or non-positive price")
            continue
        cw5, cw1 = nums.get("cache_write_5m"), nums.get("cache_write_1h")
        price = PagePrice(inp, out, read, cw5 if cw5 and cw5 > 0 else None,
                          cw1 if cw1 and cw1 > 0 else None)
        if model in result.prices and result.prices[model] != price:
            return ParseResult(error=f"{model} appears twice with different prices")
        result.prices[model] = price
    if not result.prices:
        return ParseResult(skipped=result.skipped, error="the price table held no readable model rows")
    return result
