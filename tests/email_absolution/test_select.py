"""rules.py select / show / constraints / overrides (WF-266)."""
import re
import subprocess
import sys

import pytest

from conftest import DOCTRINES, SCRIPTS


def ids_of(R, docs, **kw):
    cfg = R.Config(**kw)
    active, filt, warns = R.select_rules(docs, cfg)
    return {r.id for r in active}, filt, warns


# ---- the matrix from the design -------------------------------------------------

def test_klaviyo_liquid_marketing_gmail(R, docs):
    got, filt, warns = ids_of(R, docs, email_type="marketing", esp="klaviyo", templating="liquid",
                              targets=("gmail",))
    assert "LIQ-012" in got and "LIQ-019" in got
    assert "HBS-003" not in got and "HBS-004" not in got
    assert not any(i.startswith(("HBS-", "MJML-", "MZL-", "REMAIL-")) for i in got)
    assert "RENDER-014" not in got and "RENDER-013" not in got  # outlook-2019 only
    assert filt["targets"] > 0 and not warns


def test_sendgrid_handlebars_transactional_outlook_and_gmail(R, docs):
    got, _, _ = ids_of(R, docs, email_type="transactional", esp="sendgrid", templating="handlebars",
                       targets=("outlook-2019", "gmail"))
    assert "HBS-003" in got and "HBS-017" in got
    assert "HBS-004" not in got
    assert "RENDER-014" in got and "RENDER-013" in got
    assert not any(i.startswith("LIQ-") for i in got)


def test_postmark_handlebars(R, docs):
    got, _, _ = ids_of(R, docs, email_type="transactional", esp="postmark", templating="handlebars")
    assert "HBS-004" in got and "HBS-003" not in got and "TOOL-008" in got


def test_mjml_html_templating(R, docs):
    mj, _, _ = ids_of(R, docs, email_type="marketing", esp="custom", templating="mjml")
    assert any(i.startswith("MJML-") for i in mj) and not any(i.startswith("LIQ-") for i in mj)
    plain, _, _ = ids_of(R, docs, email_type="marketing", templating="html")
    assert not any(i.startswith(("LIQ-", "HBS-", "MJML-", "MZL-", "REMAIL-")) for i in plain)
    assert "RENDER-001" in plain


def test_empty_config_filters_nothing_but_aliases(R, docs, rules):
    got, filt, warns = ids_of(R, docs, email_type="marketing")
    assert len(got) == 248 - 9
    assert filt["alias"] == 9 and filt["esp"] == filt["targets"] == filt["templating"] == 0
    assert not warns


def test_aliases_and_template_never_emitted(R, docs, rules):
    got, _, _ = ids_of(R, docs, email_type="transactional", esp="klaviyo", templating="liquid")
    assert not got & {r.id for r in rules if r.is_alias}
    assert not any(i.startswith("PREFIX-") for i in got)  # _template.md rules are absent


def test_severity_equals_the_active_track(R, docs, by_id):
    t = R.render_select(docs, R.Config(email_type="transactional"))
    m = R.render_select(docs, R.Config(email_type="marketing"))
    for text, track in ((t, "transactional"), (m, "marketing")):
        for line in text.splitlines():
            mm = re.match(r"^([A-Z]+-\d{3}) \| (mortal|venial|counsel) \|", line)
            if mm:
                assert mm.group(2) == by_id[mm.group(1)].severity(track), line
    assert re.search(r"^RENDER-016 \| venial", t, re.M) is None  # M/M now
    assert re.search(r"^RENDER-016 \| mortal", m, re.M)
    assert re.search(r"^HTML-003 \| mortal", t, re.M) and re.search(r"^HTML-003 \| venial", m, re.M)


def test_hybrid_appears_in_both_lists(R, docs):
    text = R.render_select(docs, R.Config(email_type="marketing"))
    reg, ctx = text.split("## CONTEXTUAL")
    assert re.search(r"^HTML-003 \|", reg, re.M) and re.search(r"^HTML-003 \|", ctx, re.M)
    assert re.search(r"^HTML-023 \|", reg, re.M) and re.search(r"^HTML-023 \|", ctx, re.M)
    assert re.search(r"^GOTCHA-028 \|", ctx, re.M) and not re.search(r"^GOTCHA-028 \|", reg, re.M)


def test_header_counts_and_reasons(R, docs):
    text = R.render_select(docs, R.Config(email_type="marketing", esp="klaviyo", templating="liquid",
                                          targets=("gmail",)))
    head = text.splitlines()[0]
    m = re.match(r"# doctrines: .* \| (\d+) active, (\d+) filtered \((.*)\)$", head)
    assert m, head
    assert int(m.group(1)) + int(m.group(2)) == 248
    assert "esp:" in m.group(3) and "templating:" in m.group(3) and "alias:9" in m.group(3)


def test_doctrine_filter(R, docs):
    got, filt, _ = ids_of(R, docs, email_type="marketing", doctrine="rendering")
    assert got and all(i.startswith("RENDER-") for i in got)
    assert filt["doctrine"] > 0


def test_every_active_rule_is_listed_exactly_once_per_kind(R, docs):
    cfg = R.Config(email_type="transactional", esp="klaviyo", templating="liquid", targets=("outlook-2019",))
    active, _, _ = R.select_rules(docs, cfg)
    text = R.render_select(docs, cfg)
    reg, ctx = text.split("## CONTEXTUAL")
    for r in active:
        in_reg = len(re.findall(rf"^{r.id} \|", reg, re.M))
        in_ctx = len(re.findall(rf"^{r.id} \|", ctx, re.M))
        if r.detect.kind == "contextual":
            assert (in_reg, in_ctx) == (0, 1), r.id
        elif r.detect.kind == "hybrid":
            assert in_reg >= 1 and in_ctx == 1, r.id
        else:
            assert in_reg >= 1 and in_ctx == 0, r.id


# ---- fail-safe on unknown config values (verdict 5) -----------------------------

def test_unknown_target_disables_target_filtering_with_a_warning(R, docs):
    got, filt, warns = ids_of(R, docs, email_type="marketing", targets=("outlook-2016", "gmail"))
    assert "RENDER-014" in got and filt["targets"] == 0
    assert len(warns) == 1 and warns[0].startswith("warning:") and "outlook-2016" in warns[0]
    text = R.render_select(docs, R.Config(email_type="marketing", targets=("outlook",)))
    assert "warning: unknown rendering_targets outlook" in text


def test_unknown_templating_disables_templating_filtering(R, docs):
    got, filt, warns = ids_of(R, docs, email_type="marketing", templating="jinja")
    assert any(i.startswith("LIQ-") for i in got) and any(i.startswith("HBS-") for i in got)
    assert filt["templating"] == 0 and warns and "templating" in warns[0]


def test_unknown_esp_still_filters_but_warns(R, docs):
    got, _, warns = ids_of(R, docs, email_type="marketing", esp="braze")
    assert "HBS-003" not in got and "LIQ-012" not in got
    assert warns and "braze" in warns[0]


def test_typo_never_drops_every_outlook_rule(R, docs):
    typo, _, _ = ids_of(R, docs, email_type="marketing", targets=("outlook",))
    full, _, _ = ids_of(R, docs, email_type="marketing")
    assert typo == full


# ---- gen is not an audit filter (verdict 8) -------------------------------------

def test_select_ignores_gen_constraints_honours_it(R, docs):
    got, _, _ = ids_of(R, docs, email_type="marketing")
    assert "DELIV-001" in got  # audits still check SPF
    text = R.render_constraints(docs, R.Config(email_type="marketing"))
    assert "DELIV-001" not in text and "DELIV-002" not in text
    assert "DELIV-012" in text                      # address in the footer is generatable
    assert "TOOL-" not in text                      # tooling.md is scribe: skip
    assert "UX-" in text                            # content-ux is constraints
    assert "SPF" not in text


def test_constraints_sections_follow_the_active_track(R, docs):
    t = R.render_constraints(docs, R.Config(email_type="transactional"))
    assert "## MORTAL" in t and "## VENIAL" in t and "## COUNSEL" in t
    mortal = t.split("## VENIAL")[0]
    assert "RENDER-010" in mortal and "GOTCHA-002" not in mortal   # 80 KB margin is venial
    assert "GOTCHA-002" in t.split("## VENIAL")[1].split("## COUNSEL")[0]


# ---- show -----------------------------------------------------------------------

def test_show_prints_block_with_location(R, docs):
    text, missing = R.render_show(docs, ["GOTCHA-012", "hbs-003"])
    assert not missing
    assert re.search(r"<!-- gotchas\.md:\d+ -->", text) and "**[GOTCHA-012]**" in text
    assert "float" in text and "**[HBS-003]**" in text and "`applies: esp=sendgrid`" in text


def test_show_unknown_id_exits_2():
    r = subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "show", "NOPE-001"],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "NOPE-001" in r.stderr


def test_show_alias_block_names_its_canonical(R, docs):
    text, _ = R.render_show(docs, ["GOTCHA-001"])
    assert "`alias of RENDER-001`" in text and "detect:" not in text


def test_cli_select_runs(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "select", "--email-type", "marketing",
                        "--esp", "klaviyo", "--templating", "liquid", "--targets", "gmail,apple-mail"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("# doctrines:") and "## REGEX" in r.stdout
    assert len(r.stdout) < 80_000


def test_cli_select_requires_email_type():
    r = subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "select"], capture_output=True, text=True)
    assert r.returncode != 0


def test_select_on_unparseable_doctrines_exits_3(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "x.md").write_text("# no front matter\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "--doctrines-dir", str(d), "select",
                        "--email-type", "marketing"], capture_output=True, text=True)
    assert r.returncode == 3


# ---- alias override precedence (verdict 9) --------------------------------------

def test_override_on_alias_resolves_to_canonical(R, docs):
    out, notes = R.resolve_overrides({"GOTCHA-001": {"severity": "venial"}}, docs)
    assert out == {"RENDER-001": {"severity": "venial"}} and not notes


def test_canonical_entry_wins_when_both_are_keyed(R, docs):
    ov = {"GOTCHA-001": {"severity": "counsel"}, "RENDER-001": {"severity": "venial"}}
    out, notes = R.resolve_overrides(ov, docs)
    assert out == {"RENDER-001": {"severity": "venial"}}
    assert len(notes) == 1 and "GOTCHA-001" in notes[0] and "RENDER-001" in notes[0]
    # deterministic regardless of dict order
    out2, _ = R.resolve_overrides(dict(reversed(list(ov.items()))), docs)
    assert out2 == out


def test_unknown_override_ids_pass_through(R, docs):
    out, notes = R.resolve_overrides({"ZZZ-999": {"severity": "venial"}}, docs)
    assert out == {"ZZZ-999": {"severity": "venial"}} and not notes
