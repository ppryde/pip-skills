from scripts.contract import Finding
from scripts.matching import match


def _f(line, id_="GEN-001", category="correctness", severity="error",
       file="a.py", rule_id="GEN-001", reviewer="general", rule="r"):
    return Finding(reviewer=reviewer, id=id_, file=file, rule=rule, actual="x",
                   severity=severity, category=category, suggestion="s",
                   line=line, rule_id=rule_id)


def test_pairs_inside_window_edge_and_not_outside():
    r = match([_f(10)], [_f(13)])
    assert len(r.agreed) == 1 and not r.only_a and not r.only_b
    r = match([_f(10)], [_f(14)])
    assert not r.agreed and len(r.only_a) == 1 and len(r.only_b) == 1


def test_custom_window():
    assert len(match([_f(10)], [_f(15)], window=5).agreed) == 1


def test_agreed_keeps_a_and_higher_severity_and_confirms():
    r = match([_f(10, severity="warning", id_="A")], [_f(11, severity="error", id_="B")])
    f = r.agreed[0]
    assert f.id == "A" and f.severity == "error"
    assert f.verdict == "confirmed" and f.reason == "both passes"


def test_same_rule_or_category_required():
    other = _f(10, id_="GEN-004", rule_id="GEN-004", category="security")
    assert not match([_f(10)], [other]).agreed
    # different rule id, same category: pairs
    same_cat = _f(10, id_="GEN-002", rule_id="GEN-002")
    assert len(match([_f(10)], [same_cat]).agreed) == 1
    # same rule id, different category: pairs
    same_rule = _f(10, category="other")
    assert len(match([_f(10)], [same_rule]).agreed) == 1


def test_different_file_or_reviewer_never_pair():
    assert not match([_f(10)], [_f(10, file="b.py")]).agreed
    assert not match([_f(10)], [_f(10, reviewer="other")]).agreed


def test_none_lines_pair_only_on_equal_rule():
    assert len(match([_f(None)], [_f(None)]).agreed) == 1
    a = _f(None, rule_id=None, rule="Null deref")
    b = _f(None, rule_id=None, rule="  null   DEREF ")
    assert len(match([a], [b]).agreed) == 1
    c = _f(None, id_="GEN-004", rule_id="GEN-004", rule="other", category="security")
    assert not match([_f(None)], [c]).agreed


def test_none_versus_number_never_pairs():
    assert not match([_f(None)], [_f(5)]).agreed


def test_duplicates_within_one_pass_pair_one_to_one():
    r = match([_f(10), _f(11)], [_f(10)])
    assert len(r.agreed) == 1 and len(r.only_a) == 1 and not r.only_b


def test_prefers_nearest_candidate():
    r = match([_f(10, id_="A")], [_f(12, id_="far"), _f(10, id_="near")])
    assert len(r.agreed) == 1
    assert [f.id for f in r.only_b] == ["far"]


def test_empty_inputs():
    r = match([], [_f(1)])
    assert r.agreed == [] and len(r.only_b) == 1
