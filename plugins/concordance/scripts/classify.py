"""Is a Python change a pure refactor? Compare normalised syntax trees of one definition.

Normalised away: formatting, comments, the docstring, the definition's own name and the names
of local variables (not parameters: renaming a parameter changes the call contract).
"""
from __future__ import annotations

import ast
import copy

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _find(source: str, line: int) -> ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, _DEFS) and node.lineno == line:
            return node
    return None


def _body(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[ast.stmt]:
    body = node.body
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return body or [ast.Pass()]


class _Renamer(ast.NodeTransformer):
    def __init__(self, names: dict[str, str]) -> None:
        self.names = names

    def visit_Name(self, node: ast.Name) -> ast.Name:
        node.id = self.names.get(node.id, node.id)
        return node


def fingerprint(source: str, line: int) -> str | None:
    found = _find(source, line)
    if found is None:
        return None
    node = copy.deepcopy(found)
    node.body = _body(node)
    node.name = "_"
    if not isinstance(node, ast.ClassDef):
        params = {a.arg for a in ast.walk(node.args) if isinstance(a, ast.arg)}
        for n in ast.walk(node):  # global/nonlocal names are not locals: never rename them
            if isinstance(n, (ast.Global, ast.Nonlocal)):
                params.update(n.names)
        order: list[str] = []
        for n in ast.walk(node):
            if (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
                    and n.id not in params and n.id not in order):
                order.append(n.id)
        node = _Renamer({name: f"_v{i}" for i, name in enumerate(order)}).visit(node)
    return ast.dump(node, include_attributes=False)


def behaviour_changed(base_src: str, base_line: int, head_src: str, head_line: int) -> bool:
    a = fingerprint(base_src, base_line)
    b = fingerprint(head_src, head_line)
    return a is None or b is None or a != b


def reordered(base_src: str, base_line: int, head_src: str, head_line: int) -> bool:
    a, b = _find(base_src, base_line), _find(head_src, head_line)
    if a is None or b is None:
        return False
    sa = [ast.dump(s, include_attributes=False) for s in _body(a)]
    sb = [ast.dump(s, include_attributes=False) for s in _body(b)]
    return sa != sb and sorted(sa) == sorted(sb)
