from __future__ import annotations


def mk(batching, name, n, cats=None, scope=("a.md",)):
    ids = tuple(f"{name}-{i}" for i in range(n))
    return batching.Unit(name, ids, tuple(cats) if cats else (), tuple(scope))


def test_constants(batching):
    assert batching.BATCH_CAP == 30
    assert batching.BATCH_FLOOR == 8


def test_cap_and_tiling(batching):
    cats = ["a"] * 14 + ["b"] * 14 + ["c"] * 40 + ["d"] * 5
    units = [mk(batching, "big", len(cats), cats), mk(batching, "mid", 20), mk(batching, "flat", 95)]
    batches = batching.plan_batches(units)
    assert all(0 < b.size <= batching.BATCH_CAP for b in batches)
    by_name = {u.name: u for u in units}
    for u in units:
        spans = [s for b in batches for s in b.spans if s.unit == u.name]
        assert spans[0].start == 0 and spans[-1].end == len(u.rule_ids)
        assert all(x.end == y.start for x, y in zip(spans, spans[1:]))  # tiles exactly, in order
    # category order is respected: a, b stay together (28), c is cut at the cap and its tail joins d
    big = [s for b in batches for s in b.spans if s.unit == "big"]
    assert [(s.start, s.end) for s in big] == [(0, 28), (28, 58), (58, 73)]
    assert [rid for b in batches for rid in b.ids(by_name)].count("mid-0") == 1


def test_floor_packing_same_scope_only(batching):
    same = [mk(batching, "s1", 3), mk(batching, "s2", 4), mk(batching, "s3", 2)]
    packed = batching.plan_batches(same)
    assert len(packed) == 1 and {s.unit for s in packed[0].spans} == {"s1", "s2", "s3"}
    mixed = [mk(batching, "x", 3, scope=("a.md",)), mk(batching, "y", 3, scope=("b.md",))]
    assert len(batching.plan_batches(mixed)) == 2
    at_floor = [mk(batching, "p", batching.BATCH_FLOOR), mk(batching, "q", 3)]
    assert len(batching.plan_batches(at_floor)) == 2  # a unit at the floor is never packed
    many = [mk(batching, f"u{i}", 7) for i in range(6)]  # 42 small rules, identical scope: cap holds
    assert [b.size for b in batching.plan_batches(many)] == [28, 14]


def test_duplicate_unit_names_refused(batching):
    import pytest

    with pytest.raises(ValueError):
        batching.plan_batches([mk(batching, "d", 3), mk(batching, "d", 4)])
