from scripts.render import Section, est_tokens, render


def test_seeds_render_whole_even_over_budget() -> None:
    out = render(["H"], [Section("Verdicts", ["v" * 90] * 5, seed=True)], ["F"], budget_tokens=10)
    assert out.count("v" * 90) == 5 and out.startswith("H") and out.endswith("F")


def test_rows_are_cut_whole_with_an_exact_tail() -> None:
    rows = [f"row {i:02d} " + "x" * 20 for i in range(20)]
    out = render([], [Section("Callers", rows)], [], budget_tokens=60)
    shown = [r for r in rows if r in out]
    assert 0 < len(shown) < 20
    assert f"+{20 - len(shown)} more (exact)" in out
    assert est_tokens(out) <= 60


def test_lower_bound_tail_and_true_totals() -> None:
    out = render([], [Section("Hits", ["a"], total=7, exact=False)], [], budget_tokens=100)
    assert "## Hits (7+)" in out and "+6 more (≥)" in out


def test_a_big_early_section_does_not_starve_later_ones() -> None:
    big = Section("Callers", [f"caller {i} " + "y" * 60 for i in range(30)])
    later = [Section("Changed literals", ["lit row"]), Section("Removed comments", ["# why"])]
    out = render([], [big, *later], [], budget_tokens=200)
    assert "## Changed literals (1)" in out and "lit row" in out
    assert "## Removed comments (1)" in out and "# why" in out
    assert "caller 0 " in out and "more (exact)" in out
    assert est_tokens(out) <= 200


def test_only_sections_whose_header_cannot_fit_are_omitted() -> None:
    out = render(["h" * 140], [Section("Second", ["z"])], [], budget_tokens=50)
    assert "omitted for budget: Second (1)" in out and "## Second" not in out


def test_stats_record_what_was_cut() -> None:
    stats: dict[str, object] = {}
    rows = [f"row {i} " + "x" * 30 for i in range(10)]
    render([], [Section("Callers", rows)], [], budget_tokens=40, stats=stats)
    assert stats["budget"] == 40 and stats["omitted"] == []
    cut = stats["cut"]
    assert isinstance(cut, dict) and 0 < cut["Callers"] < 10


def test_empty_sections_are_dropped() -> None:
    assert "Nothing" not in render([], [Section("Nothing", [])], [], 100)
