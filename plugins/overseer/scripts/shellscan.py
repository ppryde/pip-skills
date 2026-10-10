"""Shell-aware command scanner for the PreToolUse guard (WF-265 PR A).

``scan(command)`` splits a bash command line into simple commands the way bash
would, tracking ``'`` / ``"`` / backslash state in ONE pass, so the guard can
tell a ``$(`` that bash will run from one that sits inert inside single quotes.
It is deliberately a *subset* parser: anything it does not model fails CLOSED
(``Scan.error``) because the guard now trusts its quote state — a scanner that
disagrees with bash about where a quote ends would hide a live substitution.

Rules (verdict changes 1-4):

* ``$(``, backtick, ``<(`` and ``>(`` are *live* outside single quotes (and in
  double quotes, and in unquoted-delimiter heredoc bodies). Inside single
  quotes or a quoted-delimiter heredoc body they are inert.
* An unquoted newline separates commands, exactly like ``;``.
* ``$'...'`` / ``$"..."``, unbalanced quotes, an unterminated heredoc, a
  redirect with no target, unquoted ``(`` ``)`` ``{`` ``}`` and any ``${...}``
  that is not a plain name are errors, never guesses.
* Heredocs: the delimiter is the dequoted word; any quote or backslash in it
  makes the body inert; the body starts after the next unquoted newline (the
  rest of the operator's line is still scanned, so ``cat <<'EOF' > /repo/x``
  still shows the redirect); several ``<<`` on one line take bodies in order;
  the terminator is the whole line (``<<-`` strips leading tabs only); an
  unquoted-delimiter body is scanned for live substitution only, honouring
  backslash escapes and backslash-newline continuation.
* ``#`` at the start of a word is a comment to the end of the line (the
  newline still separates).
* ``<<<`` is a here-string: its operand is an ordinary word, not a heredoc.

Words come back dequoted, with a per-word flag for an unquoted glob character
(``*``, ``?``, ``[``). Redirects are returned separately from words.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_PLAIN_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")
_FD_DIGITS = re.compile(r"[0-9]+")
SEPARATORS_KEEPING_CWD = frozenset({";", "&&", "\n"})


@dataclass(frozen=True)
class Redirect:
    op: str  # > >> >| &> &>> >& < <> <&
    target: str
    glob: bool = False
    fd_dup: bool = False  # ``2>&1`` / ``>&2`` / ``>&-``: no file involved

    @property
    def writes(self) -> bool:
        """Opens the target for writing (``<>`` is read-write)."""
        return not self.fd_dup and self.op != "<" and self.op != "<&"


@dataclass(frozen=True)
class Command:
    words: tuple[str, ...]
    globs: tuple[bool, ...]
    redirects: tuple[Redirect, ...] = ()
    sep: str = ""  # the separator that FOLLOWED this command ('' at the end)


@dataclass(frozen=True)
class Scan:
    commands: tuple[Command, ...] = ()
    live: bool = False  # a substitution bash would run
    error: str | None = None  # the scanner could not model the command


@dataclass
class _State:
    s: str
    i: int = 0
    live: bool = False
    error: str | None = None
    commands: list[Command] = field(default_factory=list)
    # current word
    buf: list[str] = field(default_factory=list)
    in_word: bool = False
    quoted: bool = False
    glob: bool = False
    # current command
    words: list[str] = field(default_factory=list)
    globs: list[bool] = field(default_factory=list)
    redirects: list[Redirect] = field(default_factory=list)
    pending: str | None = None  # a redirect operator awaiting its target word
    heredocs: list[tuple[str, bool, bool]] = field(default_factory=list)

    def fail(self, why: str) -> None:
        if self.error is None:
            self.error = why

    def add(self, text: str, *, quoted: bool = False, glob: bool = False) -> None:
        self.in_word = True
        self.buf.append(text)
        self.quoted = self.quoted or quoted
        self.glob = self.glob or glob

    def finish_word(self) -> None:
        if not self.in_word:
            return
        word, quoted, glob = "".join(self.buf), self.quoted, self.glob
        self.buf, self.in_word, self.quoted, self.glob = [], False, False, False
        op = self.pending
        if op is None:
            self.words.append(word)
            self.globs.append(glob)
            return
        self.pending = None
        if op in ("<<", "<<-"):
            self.heredocs.append((word, op == "<<-", quoted))
        elif op == "<<<":
            pass  # a here-string operand: scanned like any word, not a file
        else:
            dup = op in (">&", "<&") and (_FD_DIGITS.fullmatch(word) is not None or word == "-")
            self.redirects.append(Redirect(op, word, glob, dup))

    def end_command(self, sep: str) -> None:
        self.finish_word()
        if self.pending is not None:
            self.fail("redirect without a target")
            self.pending = None
        if self.words or self.redirects:
            self.commands.append(
                Command(tuple(self.words), tuple(self.globs), tuple(self.redirects), sep)
            )
        self.words, self.globs, self.redirects = [], [], []


def scan(command: str) -> Scan:
    st = _State(command)
    _run(st)
    return Scan(tuple(st.commands), st.live, st.error)


def _run(st: _State) -> None:
    s, n = st.s, len(st.s)
    while st.i < n and st.error is None:
        c = s[st.i]
        if c == "\\":
            _backslash(st)
        elif c == "'":
            end = s.find("'", st.i + 1)
            if end < 0:
                st.fail("unbalanced single quote")
                return
            st.add(s[st.i + 1:end], quoted=True)
            st.i = end + 1
        elif c == '"':
            _double_quoted(st)
        elif c in " \t":
            st.finish_word()
            st.i += 1
        elif c == "\n":
            st.end_command("\n")
            st.i += 1
            if st.heredocs:
                _heredoc_bodies(st)
        elif c == "#" and not st.in_word:
            end = s.find("\n", st.i)
            st.i = n if end < 0 else end
        elif c == ";":
            st.end_command(";")
            st.i += 1
        elif c == "&":
            _ampersand(st)
        elif c == "|":
            sep = "||" if s.startswith("||", st.i) else "|&" if s.startswith("|&", st.i) else "|"
            st.end_command(sep)
            st.i += len(sep)
        elif c in "<>":
            _redirect(st)
        elif c == "`":
            st.live = True
            st.add(c)
            st.i += 1
        elif c == "$":
            _dollar(st)
        elif c in "(){}":
            if st.live:  # already denied for substitution; keep scanning for push detection
                st.add(c)
                st.i += 1
            else:
                st.fail(f"unmodelled shell syntax {c!r}")
        elif c in "*?[":
            st.add(c, glob=True)
            st.i += 1
        else:
            st.add(c)
            st.i += 1
    if st.error is not None:
        return
    st.finish_word()
    if st.heredocs:
        st.fail("unterminated heredoc")
        return
    st.end_command("")


def _backslash(st: _State) -> None:
    s, i = st.s, st.i
    if i + 1 >= len(s):
        st.fail("trailing backslash")
        return
    nxt = s[i + 1]
    if nxt != "\n":  # backslash-newline is a continuation: the word carries on
        st.add(nxt, quoted=True)
    st.i += 2


def _dollar(st: _State) -> None:
    s, i = st.s, st.i
    nxt = s[i + 1:i + 2]
    if nxt == "(":
        st.live = True
        st.add("$(")
        st.i += 2
    elif nxt in ("'", '"'):
        st.fail("$'...' / $\"...\" quoting")
    elif nxt == "{":
        end = s.find("}", i + 2)
        body = s[i + 2:end] if end >= 0 else ""
        if end >= 0 and _PLAIN_NAME.fullmatch(body):
            st.add(s[i:end + 1])
            st.i = end + 1
            return
        if "$(" in body or "`" in body or end < 0 and ("$(" in s[i:] or "`" in s[i:]):
            st.live = True
        st.fail("unmodelled parameter expansion")
    else:
        st.add("$")
        st.i += 1


def _double_quoted(st: _State) -> None:
    s, n = st.s, len(st.s)
    i = st.i + 1
    st.in_word = True
    st.quoted = True
    while i < n:
        c = s[i]
        if c == '"':
            st.i = i + 1
            return
        if c == "\\":
            if i + 1 >= n:
                break
            nxt = s[i + 1]
            if nxt == "\n":
                i += 2
                continue
            if nxt in '$`"\\':
                st.buf.append(nxt)
                i += 2
                continue
            st.buf.append("\\")
            i += 1
            continue
        if c == "`":
            st.live = True
        elif c == "$":
            nxt = s[i + 1:i + 2]
            if nxt == "(":
                st.live = True
            elif nxt == "{":
                end = s.find("}", i + 2)
                if end < 0 or not _PLAIN_NAME.fullmatch(s[i + 2:end]):
                    # a nested quote inside ${...} would desynchronise our quote
                    # state from bash's: refuse rather than guess
                    st.fail("unmodelled parameter expansion")
                    return
        st.buf.append(c)
        i += 1
    st.fail("unbalanced double quote")


def _ampersand(st: _State) -> None:
    s, i = st.s, st.i
    if s.startswith("&>>", i) or s.startswith("&>", i):
        op = "&>>" if s.startswith("&>>", i) else "&>"
        st.finish_word()
        _set_pending(st, op)
        st.i += len(op)
        return
    sep = "&&" if s.startswith("&&", i) else "&"
    st.end_command(sep)
    st.i += len(sep)


def _redirect(st: _State) -> None:
    s, i = st.s, st.i
    c = s[i]
    # an unquoted all-digit word glued to the operator is a file descriptor
    if st.in_word and not st.quoted and _FD_DIGITS.fullmatch("".join(st.buf)):
        st.buf, st.in_word, st.glob = [], False, False
    else:
        st.finish_word()
    if s[i + 1:i + 2] == "(":
        st.live = True  # process substitution
        st.add(c + "(")
        st.i += 2
        return
    if c == ">":
        op = next(o for o in (">>", ">|", ">&", ">") if s.startswith(o, i))
    else:
        op = next(o for o in ("<<<", "<<-", "<<", "<>", "<&", "<") if s.startswith(o, i))
    _set_pending(st, op)
    st.i += len(op)


def _set_pending(st: _State, op: str) -> None:
    if st.pending is not None:
        st.fail("redirect without a target")
    st.pending = op


def _heredoc_bodies(st: _State) -> None:
    """Consume the bodies of every heredoc opened on the line just ended."""
    s, n = st.s, len(st.s)
    for delim, strip_tabs, quoted in st.heredocs:
        pos = st.i
        body_parts: list[str] = []
        found = False
        while pos < n:
            nl = s.find("\n", pos)
            line = s[pos:] if nl < 0 else s[pos:nl]
            nxt = n if nl < 0 else nl + 1
            if not quoted:  # backslash-newline joins lines in an unquoted body
                while _odd_trailing_backslashes(line) and nxt < n:
                    nl2 = s.find("\n", nxt)
                    more = s[nxt:] if nl2 < 0 else s[nxt:nl2]
                    line = line[:-1] + more
                    nxt = n if nl2 < 0 else nl2 + 1
            probe = line.lstrip("\t") if strip_tabs else line
            if probe == delim:
                found = True
                pos = nxt
                break
            body_parts.append(line)
            pos = nxt
        if not found:
            st.fail("unterminated heredoc")
            return
        if not quoted and _body_is_live("\n".join(body_parts)):
            st.live = True
        st.i = pos
    st.heredocs = []


def _odd_trailing_backslashes(line: str) -> bool:
    return (len(line) - len(line.rstrip("\\"))) % 2 == 1


def _body_is_live(body: str) -> bool:
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            return True
        if c in "$<>" and body[i + 1:i + 2] == "(":
            return True
        i += 1
    return False
