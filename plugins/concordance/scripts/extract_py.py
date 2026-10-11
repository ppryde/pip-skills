"""Python facts from one file, by stdlib ast and tokenize. Nothing is imported or executed.

Facts depend on this file's path and content only, so they can be shared by every worktree
that holds the same blob. Cross-file resolution happens later, at query time (resolve.py).
"""
from __future__ import annotations

import ast
import io
import tokenize
from pathlib import PurePosixPath

from scripts.facts import CallShape, FileFacts, Guard, Literal, Param, Ref, Signature, Symbol

_MIN_LITERAL = 3
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if parts and parts[0] == "src":
        parts.pop(0)
    return ".".join(parts) or "__root__"


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path)
    return (
        "tests" in p.parts[:-1]
        or "test" in p.parts[:-1]
        or p.name.startswith("test_")
        or p.name.endswith("_test.py")
        or p.name == "conftest.py"
    )


def extract_python(path: str, blob_sha: str, data: bytes) -> FileFacts:
    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return FileFacts(path, blob_sha, "python", False,
                         f"not UTF-8: {exc.reason} at byte {exc.start}")
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as exc:
        line = getattr(exc, "lineno", None)
        msg = getattr(exc, "msg", None) or str(exc)
        return FileFacts(path, blob_sha, "python", False, f"SyntaxError: line {line}: {msg}")
    ex = _Extractor(path, source, tree)
    ex.run()
    return FileFacts(path, blob_sha, "python", True, None,
                     ex.symbols, ex.refs, ex.literals, ex.guards)


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _shape(node: ast.Call) -> CallShape:
    return CallShape(
        positional=sum(1 for a in node.args if not isinstance(a, ast.Starred)),
        keywords=tuple(k.arg for k in node.keywords if k.arg is not None),
        star=any(isinstance(a, ast.Starred) for a in node.args),
        dstar=any(k.arg is None for k in node.keywords),
    )


def _signature(a: ast.arguments) -> Signature:
    params: list[Param] = []
    positional = [*a.posonlyargs, *a.args]
    first_default = len(positional) - len(a.defaults)
    for i, arg in enumerate(positional):
        kind = "posonly" if i < len(a.posonlyargs) else "pos"
        params.append(Param(arg.arg, kind, i >= first_default))
    if a.vararg:
        params.append(Param(a.vararg.arg, "vararg", True))
    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        params.append(Param(arg.arg, "kwonly", default is not None))
    if a.kwarg:
        params.append(Param(a.kwarg.arg, "varkw", True))
    return tuple(params)


class _Extractor(ast.NodeVisitor):
    def __init__(self, path: str, source: str, tree: ast.Module) -> None:
        self.module = module_name(path)
        self.is_pkg = PurePosixPath(path).name == "__init__.py"
        self.is_test = is_test_path(path)
        self.source = source
        self.tree = tree
        self.imports: dict[str, str] = {}
        self.module_imports: list[tuple[str, str]] = []
        self.top_defs: set[str] = set()
        self.docstrings: set[int] = set()
        self.stack: list[tuple[str, str]] = []
        self.symbols: list[Symbol] = []
        self.refs: list[Ref] = []
        self.literals: list[Literal] = []
        self.guards: list[Guard] = []

    @property
    def current(self) -> str:
        return self.stack[-1][0] if self.stack else self.module

    def _class_qual(self) -> str | None:
        for qual, kind in reversed(self.stack):
            if kind == "class":
                return qual
        return None

    def _in_function(self) -> bool:
        return any(kind in ("function", "method") for _, kind in self.stack)

    def run(self) -> None:
        self._prepass()
        n_lines = max(1, len(self.source.splitlines()))
        self.symbols.append(Symbol(self.module, "module", 1, n_lines, self.is_test))
        for local, target in self.module_imports:
            self.symbols.append(Symbol(f"{self.module}.{local}", "alias", 1, 1, self.is_test,
                                       alias_of=target))
        self.visit(self.tree)
        self._comments()

    # -- pre-pass: imports, module-level names, docstrings ---------------------------------

    def _relative_base(self, level: int) -> str | None:
        parts = self.module.split(".") if self.module != "__root__" else []
        pkg = parts if self.is_pkg else parts[:-1]
        up = level - 1
        if up > len(pkg):
            return None
        return ".".join(pkg[: len(pkg) - up])

    def _import_pairs(self, node: ast.Import | ast.ImportFrom) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    pairs.append((a.asname, a.name))
                else:
                    root = a.name.split(".")[0]
                    pairs.append((root, root))
            return pairs
        base = node.module or ""
        if node.level:
            rel = self._relative_base(node.level)
            if rel is None:
                return pairs
            base = f"{rel}.{base}" if rel and base else (rel or base)
        for a in node.names:
            if a.name != "*":
                pairs.append((a.asname or a.name, f"{base}.{a.name}" if base else a.name))
        return pairs

    def _prepass(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, (*_DEFS, ast.Module)):
                body = node.body
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    self.docstrings.add(id(body[0].value))
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.imports.update(self._import_pairs(node))
        for node in self.tree.body:
            if isinstance(node, _DEFS):
                self.top_defs.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                self.top_defs.update(t.id for t in targets if isinstance(t, ast.Name))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                self.module_imports.extend(self._import_pairs(node))

    # -- name resolution within this file --------------------------------------------------

    def _resolve(self, dotted: str) -> str | None:
        head, _, rest = dotted.partition(".")
        if head in ("self", "cls"):
            cls = self._class_qual()
            if cls is None or not rest:
                return None
            return f"?.{rest.rsplit('.', 1)[-1]}" if "." in rest else f"{cls}.{rest}"
        if head in self.imports:
            base = self.imports[head]
            return f"{base}.{rest}" if rest else base
        if head in self.top_defs:
            return f"{self.module}.{dotted}"
        if rest:
            return f"?.{rest.rsplit('.', 1)[-1]}"
        return None

    def _ref(self, target: str, kind: str, line: int, args: CallShape | None = None,
             src: str | None = None) -> None:
        self.refs.append(Ref(src or self.current, target, kind, line, args))

    # -- definitions -----------------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._def(node, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._def(node, "function")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._def(node, "class")

    def _def(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, kind: str
    ) -> None:
        parent_kind = self.stack[-1][1] if self.stack else "module"
        if kind == "function" and parent_kind == "class":
            kind = "method"
        qual = f"{self.current}.{node.name}"
        sig = None if isinstance(node, ast.ClassDef) else _signature(node.args)
        self.symbols.append(Symbol(qual, kind, node.lineno, node.end_lineno or node.lineno,
                                   self.is_test, sig))
        for dec in node.decorator_list:
            func = dec.func if isinstance(dec, ast.Call) else dec
            target = self._resolve(_dotted(func) or "")
            if target:
                self._ref(target, "decorator", dec.lineno, src=qual)
            if isinstance(dec, ast.Call):
                for a in dec.args:
                    self.visit(a)
                for k in dec.keywords:
                    self.visit(k.value)
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                target = self._resolve(_dotted(base) or "")
                if target:
                    self._ref(target, "inherit", base.lineno, src=qual)
        else:
            for default in [*node.args.defaults, *node.args.kw_defaults]:
                if default is not None:
                    self.visit(default)
        self.stack.append((qual, kind))
        for stmt in node.body:
            self.visit(stmt)
        self.stack.pop()

    # -- references ------------------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        dotted = _dotted(node.func)
        target: str | None = None
        if dotted is not None:
            target = self._resolve(dotted)
        elif isinstance(node.func, ast.Attribute):
            target = f"?.{node.func.attr}"
            self.visit(node.func.value)
        else:
            self.visit(node.func)
        if target is not None:
            self._ref(target, "call", node.lineno, _shape(node))
        for a in node.args:
            self.visit(a)
        for k in node.keywords:
            self.visit(k.value)

    def visit_Name(self, node: ast.Name) -> None:
        in_scope = node.id in self.imports or node.id in self.top_defs
        if isinstance(node.ctx, ast.Load) and in_scope:
            target = self._resolve(node.id)
            if target:
                self._ref(target, "name", node.lineno)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        dotted = _dotted(node)
        if isinstance(node.ctx, ast.Load) and dotted and dotted.split(".")[0] in self.imports:
            target = self._resolve(dotted)
            if target:
                self._ref(target, "name", node.lineno)
                return
        self.generic_visit(node)

    # -- guards and literals ---------------------------------------------------------------

    def visit_If(self, node: ast.If) -> None:
        if self._in_function():
            self.guards.append(Guard(self.current, "if", node.lineno, ast.unparse(node.test)))
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        if self._in_function() and node.exc is not None:
            self.guards.append(Guard(self.current, "raise", node.lineno, ast.unparse(node.exc)))
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        if self._in_function():
            self.guards.append(
                Guard(self.current, "assert", node.lineno, ast.unparse(node.test)))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if (isinstance(node.value, str) and id(node) not in self.docstrings
                and len(node.value) >= _MIN_LITERAL):
            self.literals.append(Literal("string", node.value, node.lineno, self.current))

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                self.visit(part.value)

    def _comments(self) -> None:
        spans = sorted(
            ((s.line_start, s.line_end, s.qualname) for s in self.symbols
             if s.kind not in ("module", "alias")),
            key=lambda t: t[1] - t[0],
        )
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(self.source).readline))
        except (tokenize.TokenError, SyntaxError):
            return
        for tok in tokens:
            if tok.type != tokenize.COMMENT:
                continue
            line = tok.start[0]
            text = tok.string.lstrip("#").strip()
            if not text:
                continue
            owner = next((q for a, b, q in spans if a <= line <= b), self.module)
            self.literals.append(Literal("comment", text, line, owner))
