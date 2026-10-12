from scripts.classify import behaviour_changed, reordered

BASE = 'def f(a, b):\n    """Doc."""\n    total = a + b\n    return total\n'


def test_local_rename_and_docstring_are_a_refactor() -> None:
    head = "def f(a, b):\n    s = a + b\n    return s\n"
    assert not behaviour_changed(BASE, 1, head, 1)


def test_changed_operator_is_behaviour() -> None:
    assert behaviour_changed(BASE, 1, "def f(a, b):\n    total = a - b\n    return total\n", 1)


def test_parameter_rename_is_behaviour() -> None:
    assert behaviour_changed(BASE, 1, "def f(a, c):\n    total = a + c\n    return total\n", 1)


def test_reordered_statements() -> None:
    base = "def g():\n    a()\n    b()\n"
    head = "def g():\n    b()\n    a()\n"
    assert reordered(base, 1, head, 1) and behaviour_changed(base, 1, head, 1)
    assert not reordered(base, 1, base, 1)


def test_missing_definition_counts_as_changed() -> None:
    assert behaviour_changed(BASE, 99, BASE, 1)


def test_global_and_nonlocal_names_are_not_renamed() -> None:
    a = "def f():\n    global G\n    G = 1\n"
    assert behaviour_changed(a, 1, "def f():\n    global G\n    H = 1\n", 1)
    b = "def f():\n    global A\n    A = 1\n    B = 2\n"
    assert behaviour_changed(b, 1, "def f():\n    global A\n    B = 1\n    A = 2\n", 1)
    n = "def o():\n    x = 0\n    def f():\n        nonlocal x\n        x = 1\n    return f\n"
    assert behaviour_changed(n, 3, n.replace("x = 1", "y = 1"), 3)
