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
