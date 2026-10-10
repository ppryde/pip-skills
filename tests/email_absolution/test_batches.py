"""rules.py batches: deterministic audit batches (WF-266 PR 2, owner-approved subagent split).

Synthetic doctrines live in tmp_path; the real doctrines are only read."""
import subprocess
import sys

import pytest

from conftest import SCRIPTS

CFG = dict(email_type="marketing")


def write_doctrine(d, name, prefix, n, sections=None):
    """n rules; `sections` = list of rule counts, each opened by a `### ` heading."""
    out = [f"---\ndoctrine: {name}\nprefix: {prefix}\nkind: core\nscribe: constraints\n---\n",
           f"# {name}\n", "## Rule Catalog\n"]
    counts = sections or [n]
    k = 0
    for si, c in enumerate(counts):
        if sections:
            out.append(f"### Section {si}\n")
        for _ in range(c):
            k += 1
            out.append(f"**[{prefix}-{k:03d}]** `transactional: mortal | marketing: mortal` — Rule {k}.\n"
                       f"> Why.\n> `detect: contextual` — check {k}\n")
    (d / f"{name}.md").write_text("\n".join(out), encoding="utf-8")


@pytest.fixture()
def ddir(tmp_path):
    d = tmp_path / "doctrines"
    d.mkdir()
    return d


def batches(R, ddir, cap=None):
    docs, problems = R.load(ddir)
    assert not problems, problems
    active, _, _ = R.select_rules(docs, R.Config(**CFG))
    return active, (R.make_batches(active, cap) if cap else R.make_batches(active))


def ids(bs):
    return [[r.id for r in rules] for _, rules in bs]


def test_cap_is_one_constant(R):
    assert R.BATCH_CAP == 30 and R.BATCH_SMALL == 8


def test_one_batch_per_doctrine_and_no_rule_lost_or_duplicated(R, ddir):
    write_doctrine(ddir, "alpha", "AAA", 20)
    write_doctrine(ddir, "beta", "BBB", 12)
    active, bs = batches(R, ddir)
    assert [n for n, _ in bs] == [["alpha"], ["beta"]]
    flat = [i for b in ids(bs) for i in b]
    assert flat == [r.id for r in active] and len(set(flat)) == len(flat)


def test_over_cap_doctrine_splits_on_section_boundaries(R, ddir):
    write_doctrine(ddir, "big", "BIG", 0, sections=[12, 15, 10, 9])
    active, bs = batches(R, ddir)
    sizes = [len(b) for b in ids(bs)]
    assert sizes == [27, 19]          # sections 1+2 fit; section 3 starts a new batch
    assert all(s <= R.BATCH_CAP for s in sizes)
    assert [i for b in ids(bs) for i in b] == [r.id for r in active]


def test_oversized_section_is_split_evenly_in_order(R, ddir):
    write_doctrine(ddir, "flat", "FLT", 0, sections=[70])
    active, bs = batches(R, ddir)
    assert [len(b) for b in ids(bs)] == [24, 23, 23]
    assert [i for b in ids(bs) for i in b] == [r.id for r in active]


def test_doctrine_without_headings_splits_in_rule_order(R, ddir):
    write_doctrine(ddir, "plain", "PLN", 45)
    active, bs = batches(R, ddir)
    assert [len(b) for b in ids(bs)] == [23, 22]
    assert [i for b in ids(bs) for i in b] == [r.id for r in active]


def test_small_doctrines_share_a_batch_up_to_the_cap(R, ddir):
    for n, p in (("a1", "AAA"), ("a2", "AAB"), ("a3", "AAC"), ("a4", "AAD"), ("a5", "AAE")):
        write_doctrine(ddir, n, p, 7)
    active, bs = batches(R, ddir)
    assert [n for n, _ in bs] == [["a1", "a2", "a3", "a4"], ["a5"]]      # 28 then 7
    assert all(len(r) <= 30 for _, r in bs)


def test_eight_rule_doctrine_is_not_small(R, ddir):
    write_doctrine(ddir, "b1", "BO", 8)
    write_doctrine(ddir, "b2", "BT", 5)
    _, bs = batches(R, ddir)
    assert [n for n, _ in bs] == [["b1"], ["b2"]]


def test_cap_parameter_is_respected(R, ddir):
    write_doctrine(ddir, "c1", "CC", 25)
    write_doctrine(ddir, "c2", "CD", 3)
    write_doctrine(ddir, "c3", "CE", 3)
    active, bs = batches(R, ddir, cap=10)
    assert all(len(r) <= 10 for _, r in bs)
    assert [i for b in ids(bs) for i in b] == [r.id for r in active]
    assert [n for n, _ in bs][-1] == ["c2", "c3"]


def test_stable_across_runs(R, ddir):
    write_doctrine(ddir, "z", "ZZ", 40)
    write_doctrine(ddir, "y", "YY", 3)
    _, one = batches(R, ddir)
    _, two = batches(R, ddir)
    assert ids(one) == ids(two)


def test_real_doctrines_cover_every_active_rule_once(R, docs):
    for cfg in (R.Config("marketing"), R.Config("transactional", "klaviyo", "liquid", ("outlook-2019", "gmail")),
                R.Config("marketing", "postmark", "handlebars")):
        active, _, _ = R.select_rules(docs, cfg)
        bs = R.make_batches(active)
        flat = [r.id for _, rules in bs for r in rules]
        assert sorted(flat) == sorted(r.id for r in active) and len(set(flat)) == len(flat)
        assert all(len(rules) <= R.BATCH_CAP for _, rules in bs)


def test_ids_filter_narrows_select_and_scan(R, docs):
    active, _, _ = R.select_rules(docs, R.Config("marketing", ids=("RENDER-001", "HTML-001")))
    assert sorted(r.id for r in active) == ["HTML-001", "RENDER-001"]
    _, _, warns = R.select_rules(docs, R.Config("marketing", ids=("NOPE-999",)))
    assert any("NOPE-999" in w for w in warns)


def test_cli_batches_output_round_trips_into_select(R, ddir, tmp_path):
    write_doctrine(ddir, "alpha", "AAA", 4)
    run = lambda *a: subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "--doctrines-dir", str(ddir), *a],
                                    capture_output=True, text=True, check=True).stdout
    out = run("batches", "--email-type", "marketing").splitlines()
    assert out[0].startswith("# batches: 1 | cap 30 | 4 active rules")
    batch = out[1].split(" | ")
    assert batch[:3] == ["batch 1", "alpha", "4"]
    sel = run("select", "--email-type", "marketing", "--ids", batch[3].split(",")[0])
    assert "AAA-001 |" in sel and "AAA-002 |" not in sel
