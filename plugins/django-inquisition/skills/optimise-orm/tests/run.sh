#!/usr/bin/env bash
# Test harness for django-inquisition:optimise-orm
# Modes:
#   (no args)   — static-shape validation only (fast, CI-safe)
#   --live      — live invocation against all fixtures (requires Claude CLI + a logged-in account)
#   --fixture N — live invocation against a single fixture by number (e.g. --fixture 01)
#   --runs N    — repeat each live fixture N times (default 1)
#   --plugin-dir D — the django-inquisition plugin under test (default: this checkout).
#                    Live runs pass it to `claude -p --plugin-dir`, so an installed copy is never used.
#   --log-dir D — keep per-run transcripts, outputs and run metadata under D
# Environment: CLAUDE_BIN (default claude), CLAUDE_MODEL (passed as --model), PLUGIN_SHA (label for exports)
#
# Exit codes:
#   0  all checks passed
#   1  one or more checks failed
#   2  setup error (missing dependency, bad argument)

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TESTS_DIR="$SKILL_DIR/tests"
CHECKS_DIR="$SKILL_DIR/checks"
FIXTURES_DIR="$TESTS_DIR/fixtures"

MODE="static"
FIXTURE_FILTER=""
RUNS=1
PLUGIN_DIR="${PLUGIN_DIR:-$(cd "$SKILL_DIR/../.." && pwd)}"
LOG_DIR=""
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
CLAUDE_MODEL="${CLAUDE_MODEL:-}"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --live)
      MODE="live"
      shift
      ;;
    --fixture)
      shift
      if [[ -z "${1:-}" ]]; then
        echo "ERROR: --fixture requires a fixture number (e.g. --fixture 01)" >&2
        exit 2
      fi
      FIXTURE_FILTER="$1"
      shift
      ;;
    --runs)
      shift
      RUNS="${1:-}"
      if ! [[ "$RUNS" =~ ^[0-9]+$ ]] || [[ "$RUNS" -lt 1 ]]; then
        echo "ERROR: --runs requires a positive integer" >&2
        exit 2
      fi
      shift
      ;;
    --plugin-dir)
      shift
      if [[ -z "${1:-}" || ! -d "$1" ]]; then
        echo "ERROR: --plugin-dir requires an existing directory" >&2
        exit 2
      fi
      PLUGIN_DIR="$(cd "$1" && pwd)"
      shift
      ;;
    --log-dir)
      shift
      if [[ -z "${1:-}" ]]; then
        echo "ERROR: --log-dir requires a directory" >&2
        exit 2
      fi
      mkdir -p "$1"
      LOG_DIR="$(cd "$1" && pwd)"
      shift
      ;;
    --help|-h)
      sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# //'
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RESET='\033[0m'

pass() { echo -e "${GREEN}PASS${RESET} $*"; }
fail() { echo -e "${RED}FAIL${RESET} $*"; FAILURES=$((FAILURES + 1)); }
warn() { echo -e "${YELLOW}WARN${RESET} $*"; }

FAILURES=0

# ---------------------------------------------------------------------------
# Static-shape mode
# ---------------------------------------------------------------------------
static_shape_checks() {
  echo ""
  echo "=== Static-shape validation ==="
  echo ""

  # --- 1. SKILL.md exists ---
  if [[ -f "$SKILL_DIR/SKILL.md" ]]; then
    pass "SKILL.md exists"
  else
    fail "SKILL.md not found at $SKILL_DIR/SKILL.md"
  fi

  # --- 2. All 8 check-group files exist ---
  EXPECTED_GROUPS=(fetching cardinality aggregation writes iteration indexes joins patterns)
  for group in "${EXPECTED_GROUPS[@]}"; do
    if [[ -f "$CHECKS_DIR/$group.md" ]]; then
      pass "checks/$group.md exists"
    else
      fail "checks/$group.md not found"
    fi
  done

  # --- 3. Each check file has required YAML frontmatter fields ---
  for group in "${EXPECTED_GROUPS[@]}"; do
    local file="$CHECKS_DIR/$group.md"
    [[ -f "$file" ]] || continue

    # Extract frontmatter (between first pair of ---)
    local fm
    fm=$(awk '/^---$/{found++; if(found==2) exit} found==1{print}' "$file")

    for field in name title checks; do
      if echo "$fm" | grep -q "^${field}:"; then
        pass "checks/$group.md has frontmatter field: $field"
      else
        fail "checks/$group.md missing frontmatter field: $field"
      fi
    done
  done

  # --- 4. SKILL.md wires the INDEX and every reference file ---
  if grep -q "checks/INDEX.md" "$SKILL_DIR/SKILL.md"; then
    pass "SKILL.md references checks/INDEX.md"
  else
    fail "SKILL.md does not reference checks/INDEX.md"
  fi
  local ref
  for ref in "$SKILL_DIR"/references/*.md; do
    [[ -f "$ref" ]] || continue
    if grep -q "references/$(basename "$ref")" "$SKILL_DIR/SKILL.md"; then
      pass "SKILL.md references references/$(basename "$ref")"
    else
      fail "SKILL.md does not reference references/$(basename "$ref")"
    fi
  done

  # --- 5. INDEX.md is the single list of codes: every row has a section, every section a row ---
  # The code list is read from the generated INDEX (checks/INDEX.md), never hard-coded here.
  local index="$CHECKS_DIR/INDEX.md"
  if [[ ! -f "$index" ]]; then
    fail "checks/INDEX.md not found (run: python3 tools/build_index.py optimise-orm)"
    return
  fi
  local n_rows
  n_rows=$(grep -cE '^\| [A-Z]+-[0-9]+ \|' "$index" || true)
  if [[ "$n_rows" -gt 0 ]]; then
    pass "INDEX.md lists $n_rows checks"
  else
    fail "INDEX.md lists no checks"
  fi

  # Each row: its Span names a group file whose line at the span start is `### <CODE>`.
  local row code span_file span_start line
  while IFS= read -r row; do
    code=$(echo "$row" | grep -oE '^\| [A-Z]+-[0-9]+' | grep -oE '[A-Z]+-[0-9]+')
    span_file=$(echo "$row" | grep -oE '[a-z]+\.md L[0-9]+-[0-9]+ \|$' | grep -oE '^[a-z]+\.md')
    span_start=$(echo "$row" | grep -oE ' L[0-9]+-[0-9]+ \|$' | grep -oE '[0-9]+' | head -1)
    line=$(sed -n "${span_start}p" "$CHECKS_DIR/$span_file" 2>/dev/null || true)
    if [[ "$line" == "### $code" ]]; then
      pass "INDEX row $code -> $span_file L$span_start is its section heading"
    else
      fail "INDEX row $code: $span_file line $span_start is '$line', expected '### $code' (regenerate: python3 tools/build_index.py optimise-orm)"
    fi
  done < <(grep -E '^\| [A-Z]+-[0-9]+ \|' "$index")

  # Each group: frontmatter ids == body `### CODE` headings == INDEX rows for that file.
  for group in "${EXPECTED_GROUPS[@]}"; do
    local file="$CHECKS_DIR/$group.md"
    [[ -f "$file" ]] || continue
    local fm_ids body_ids idx_ids
    fm_ids=$(awk '/^---$/{n++; next} n==1 && /^checks:/{c=1; next} n==1 && /^aliases:/{c=0} n==1 && c && /^  - id: /{sub(/^  - id: /,""); print}' "$file" | sort | tr '\n' ' ')
    body_ids=$(grep -E '^### [A-Z]+-[0-9]+$' "$file" | sed 's/^### //' | sort | tr '\n' ' ')
    idx_ids=$(grep -E "^\| [A-Z]+-[0-9]+ \|.*\| $group\.md L[0-9]+-[0-9]+ \|\$" "$index" | grep -oE '^\| [A-Z]+-[0-9]+' | grep -oE '[A-Z]+-[0-9]+' | sort | tr '\n' ' ')
    if [[ "$fm_ids" == "$body_ids" && "$body_ids" == "$idx_ids" && -n "$body_ids" ]]; then
      pass "checks/$group.md: frontmatter ids, section headings and INDEX rows agree"
    else
      fail "checks/$group.md: ids differ (frontmatter: $fm_ids| sections: $body_ids| index: $idx_ids)"
    fi
  done

  # Every live check declares a trigger; alias targets are live checks.
  local no_trigger
  no_trigger=$( (grep -E '^\| [A-Z]+-[0-9]+ \|' "$index" | grep -v '`' || true) | grep -oE '^\| [A-Z]+-[0-9]+' | grep -oE '[A-Z]+-[0-9]+' | tr '\n' ' ' || true)
  if [[ -z "$no_trigger" ]]; then
    pass "every INDEX row has a trigger"
  else
    fail "INDEX rows without a trigger: $no_trigger"
  fi
  local target
  while IFS= read -r target; do
    [[ -z "$target" ]] && continue
    if grep -qE "^\| $target \|" "$index"; then
      pass "alias target $target is a live check"
    else
      fail "alias target $target is not a live check"
    fi
  done < <(grep -E '^- [A-Z]+-[0-9]+ -> [A-Z]+-[0-9]+$' "$index" | sed 's/.*-> //')

  # The generated INDEX is current (needs the repo-level generator; skipped for a standalone install).
  local gen="$SKILL_DIR/../../../../tools/build_index.py"
  if [[ -f "$gen" ]] && command -v python3 >/dev/null 2>&1; then
    if python3 "$gen" optimise-orm --check >/dev/null 2>&1; then
      pass "checks/INDEX.md matches the generator output"
    else
      fail "checks/INDEX.md has drifted from the group files (python3 tools/build_index.py optimise-orm --check)"
    fi
  fi

  # --- 6. Severity mapping and output rules are present in SKILL.md ---
  SEVERITY_PATTERNS=(
    "critical" "savings_midpoint" "confidence_weight" "sort_key"
    "header banner" "noqa: optimise-orm" "--thorough" "Correctness (outside the perf scope)"
  )
  for pattern in "${SEVERITY_PATTERNS[@]}"; do
    if grep -q -- "$pattern" "$SKILL_DIR/SKILL.md"; then
      pass "SKILL.md contains ranking concept: $pattern"
    else
      fail "SKILL.md missing ranking concept: $pattern"
    fi
  done

  # --- 7. Fixture directories exist (structure check only) ---
  EXPECTED_FIXTURES=(
    "01-basic-n-plus-one"
    "02-bulk-write-loop"
    "03-missing-prefetch"
    "04-column-overfetching"
    "05-missing-index-postgres"
    "06-audit-framework-bypass"
    "07-suppression-marker"
    "08-mysql-engine-degradation"
    "09-non-django-target"
    "10-symbol-resolution-ambiguous"
    "11-pghistory-no-bypass-warning"
    "12-async-orm-django-4-1"
  )
  for fixture in "${EXPECTED_FIXTURES[@]}"; do
    if [[ -d "$FIXTURES_DIR/$fixture" ]]; then
      pass "fixture directory exists: $fixture"
    else
      warn "fixture directory missing: $fixture (Django teammate may not have created it yet)"
    fi
  done

  # --- 8. Each present fixture has target.py and expected.json ---
  for fixture in "${EXPECTED_FIXTURES[@]}"; do
    local fdir="$FIXTURES_DIR/$fixture"
    [[ -d "$fdir" ]] || continue
    for required_file in target.py expected.json; do
      if [[ -f "$fdir/$required_file" ]]; then
        pass "fixture $fixture has $required_file"
      else
        fail "fixture $fixture missing $required_file"
      fi
    done
  done
}

# ---------------------------------------------------------------------------
# Live mode
# ---------------------------------------------------------------------------
live_checks() {
  echo ""
  echo "=== Live invocation ==="
  echo ""

  # Check for claude CLI
  if ! command -v "$CLAUDE_BIN" &>/dev/null; then
    echo "ERROR: '$CLAUDE_BIN' not found. Live mode requires the Claude Code CLI." >&2
    exit 2
  fi

  # python3 is required for expected.json parsing — fail loudly if missing.
  if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required for live mode (expected.json parsing)" >&2
    exit 2
  fi

  if [[ -z "$LOG_DIR" ]]; then
    LOG_DIR="$(mktemp -d "/tmp/optimise-orm-live-XXXXXX")"
  fi

  # --- Pin the plugin under test -------------------------------------------
  # `--plugin-dir` makes the headless session load THIS directory as django-inquisition
  # (it replaces any installed copy of the same name). Log what is under test, then verify
  # headless that Claude Code really loaded it, so an A/B can never compare an installed
  # copy with itself.
  local plugin_json="$PLUGIN_DIR/.claude-plugin/plugin.json" plugin_version plugin_sha
  if [[ ! -f "$plugin_json" ]]; then
    echo "ERROR: $plugin_json not found; --plugin-dir must be the django-inquisition plugin root" >&2
    exit 2
  fi
  plugin_version=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$plugin_json")
  plugin_sha="${PLUGIN_SHA:-$(git -C "$PLUGIN_DIR" rev-parse HEAD 2>/dev/null || echo unknown)}"
  local claude_args=(-p --plugin-dir "$PLUGIN_DIR" --output-format stream-json --verbose
                     --allowedTools Read Grep Glob Write Edit Bash)
  [[ -n "$CLAUDE_MODEL" ]] && claude_args+=(--model "$CLAUDE_MODEL")

  echo "  Plugin under test: $PLUGIN_DIR"
  echo "  Plugin version:    $plugin_version"
  echo "  Plugin SHA:        $plugin_sha"
  echo "  Model:             ${CLAUDE_MODEL:-<default>}   Runs per fixture: $RUNS"
  echo "  Log dir:           $LOG_DIR"
  {
    echo "plugin_dir=$PLUGIN_DIR"
    echo "plugin_version=$plugin_version"
    echo "plugin_sha=$plugin_sha"
    echo "model=${CLAUDE_MODEL:-default}"
    echo "runs=$RUNS"
    echo "started=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >"$LOG_DIR/arm.txt"

  local probe_dir loaded
  probe_dir=$(mktemp -d "/tmp/optimise-orm-probe-XXXXXX")
  (cd "$probe_dir" && "$CLAUDE_BIN" "${claude_args[@]}" "Reply with the single word ok." >"$LOG_DIR/pin-probe.jsonl" 2>"$LOG_DIR/pin-probe.err") || true
  rm -rf "$probe_dir"
  loaded=$(python3 "$TESTS_DIR/live_helpers.py" init-plugin "$LOG_DIR/pin-probe.jsonl" django-inquisition || true)
  if [[ "${loaded%%$'\t'*}" == "$PLUGIN_DIR" ]]; then
    pass "headless session loaded django-inquisition from $PLUGIN_DIR (version ${loaded#*$'\t'})"
    echo "loaded=$loaded" >>"$LOG_DIR/arm.txt"
  else
    fail "headless session did not load django-inquisition from $PLUGIN_DIR (init event said: '${loaded:-nothing}')"
    return
  fi

  # Determine which fixtures to run
  local fixtures=()
  if [[ -n "$FIXTURE_FILTER" ]]; then
    local match
    match=$(find "$FIXTURES_DIR" -maxdepth 1 -type d -name "${FIXTURE_FILTER}-*" | head -1)
    if [[ -z "$match" ]]; then
      echo "ERROR: No fixture found matching prefix: $FIXTURE_FILTER" >&2
      exit 2
    fi
    fixtures=("$match")
  else
    while IFS= read -r dir; do
      fixtures+=("$dir")
    done < <(find "$FIXTURES_DIR" -maxdepth 1 -mindepth 1 -type d | sort)
  fi

  if [[ ${#fixtures[@]} -eq 0 ]]; then
    warn "No fixture directories found in $FIXTURES_DIR"
    return
  fi

  local fixture_dir run
  for fixture_dir in "${fixtures[@]}"; do
    local fixture_name
    fixture_name=$(basename "$fixture_dir")
    echo ""
    echo "--- Fixture: $fixture_name ---"

    # Validate fixture has required files
    if [[ ! -f "$fixture_dir/target.py" ]]; then
      warn "Skipping $fixture_name — no target.py"
      continue
    fi
    if [[ ! -f "$fixture_dir/expected.json" ]]; then
      warn "Skipping $fixture_name — no expected.json"
      continue
    fi
    mkdir -p "$LOG_DIR/$fixture_name"

    for run in $(seq 1 "$RUNS"); do
      live_one_run "$fixture_dir" "$fixture_name" "$run" "${claude_args[@]}"
    done
  done
}

# live_one_run <fixture_dir> <fixture_name> <run> <claude args...>
live_one_run() {
  local fixture_dir="$1" fixture_name="$2" run="$3"
  shift 3
  local expected_path="$fixture_dir/expected.json"
  local stream="$LOG_DIR/$fixture_name/run$run.jsonl"
  local out="$LOG_DIR/$fixture_name/run$run.txt"
  local scratch
  # Each run gets its own copy of the fixture as the working directory, so the report
  # file lands in a scratch tree and nothing is written into the checkout.
  scratch=$(mktemp -d "/tmp/optimise-orm-run-XXXXXX")
  cp -R "$fixture_dir/." "$scratch/"

  # Invoke the skill with --report so we can parse frontmatter. `claude -p` is the
  # documented headless mode; the stream is kept so bytes read can be measured.
  echo "  [run $run/$RUNS] claude -p '/django-inquisition:optimise-orm $scratch/target.py --report --no-explain'"
  local meta
  if ! (cd "$scratch" && "$CLAUDE_BIN" "$@" "/django-inquisition:optimise-orm $scratch/target.py --report --no-explain" \
         >"$stream" 2>"$LOG_DIR/$fixture_name/run$run.err"); then
    fail "$fixture_name run $run — skill invocation failed (stderr: $LOG_DIR/$fixture_name/run$run.err)"
    rm -rf "$scratch"
    return
  fi
  meta=$(python3 "$TESTS_DIR/live_helpers.py" summarize "$stream" "$scratch" "$out")
  echo "$meta" >"$LOG_DIR/$fixture_name/run$run.meta.json"
  echo "  INFO: $fixture_name run $run — $meta"
  rm -rf "$scratch"

  # Parse report frontmatter findings_count
  local actual_critical actual_medium actual_low
  actual_critical=$(grep 'critical:' "$out" | head -1 | grep -o '[0-9]*' | head -1 || true)
  actual_medium=$(grep 'medium:' "$out" | head -1 | grep -o '[0-9]*' | head -1 || true)
  actual_low=$(grep 'low:' "$out" | head -1 | grep -o '[0-9]*' | head -1 || true)
  actual_critical=${actual_critical:-0}
  actual_medium=${actual_medium:-0}
  actual_low=${actual_low:-0}

  # Parse expected.json once: emit `<critical> <medium> <low>` on line 1
  # then one `<id>|<location_pattern>` per finding.
  local parsed
  if ! parsed=$(python3 - "$expected_path" <<'PY' 2>&1
import json, sys
path = sys.argv[1]
try:
    data = json.load(open(path))
except Exception as e:
    print(f"PARSE_ERROR: {e}", file=sys.stderr)
    sys.exit(1)
counts = {"critical": 0, "medium": 0, "low": 0}
for f in data:
    counts[f.get("tier_displayed", "")] = counts.get(f.get("tier_displayed", ""), 0) + 1
print(f"{counts['critical']} {counts['medium']} {counts['low']}")
for f in data:
    print(f"{f['id']}|{f.get('location_pattern', '')}")
PY
  ); then
    echo "ERROR: failed to parse $expected_path: $parsed" >&2
    exit 2
  fi

  local required_critical required_medium required_low required_pairs
  required_critical=$(echo "$parsed" | sed -n '1p' | awk '{print $1}')
  required_medium=$(echo "$parsed" | sed -n '1p' | awk '{print $2}')
  required_low=$(echo "$parsed" | sed -n '1p' | awk '{print $3}')
  required_pairs=$(echo "$parsed" | sed -n '2,$p')

  # Check critical findings (zero variance allowed per spec §7.3)
  if [[ "$actual_critical" -lt "$required_critical" ]]; then
    fail "$fixture_name run $run — critical findings: expected ≥$required_critical, got $actual_critical"
  else
    pass "$fixture_name run $run — critical findings count OK ($actual_critical)"
  fi

  # Check medium findings (≥80% threshold per spec §7.3)
  local medium_threshold=$(( required_medium * 80 / 100 ))
  if [[ "$required_medium" -gt 0 && "$actual_medium" -lt "$medium_threshold" ]]; then
    fail "$fixture_name run $run — medium findings: expected ≥${medium_threshold} (80% of $required_medium), got $actual_medium"
  elif [[ "$required_medium" -gt 0 ]]; then
    pass "$fixture_name run $run — medium findings count OK ($actual_medium / $required_medium)"
  fi

  # Low findings — informational only, not enforced
  if [[ "$required_low" -gt 0 ]]; then
    echo "  INFO: $fixture_name run $run — low findings: $actual_low (required $required_low, not enforced)"
  fi

  # Check each required (id, location_pattern) pair appears in the output.
  local code loc_pattern
  while IFS='|' read -r code loc_pattern; do
    [[ -z "$code" ]] && continue
    if grep -q "$code" "$out" && grep -q "$loc_pattern" "$out"; then
      pass "$fixture_name run $run — required finding $code @ $loc_pattern present"
    else
      fail "$fixture_name run $run — required finding $code @ $loc_pattern NOT found in output"
    fi
  done <<< "$required_pairs"

  # Optional: validate suppressed-count from expected_meta.json (fixtures
  # exercising # noqa: optimise-orm markers). Other fixtures lack this file
  # and skip silently.
  local meta_path="$fixture_dir/expected_meta.json"
  if [[ -f "$meta_path" ]]; then
    local required_suppressed actual_suppressed
    if ! required_suppressed=$(python3 -c "
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception as e:
    print(f'PARSE_ERROR: {e}', file=sys.stderr)
    sys.exit(1)
print(data.get('suppressed_count', 0))
" "$meta_path" 2>&1); then
      echo "ERROR: failed to parse $meta_path: $required_suppressed" >&2
      exit 2
    fi
    actual_suppressed=$(grep -E '^suppressed:[[:space:]]*[0-9]+' "$out" | head -1 | grep -oE '[0-9]+' || true)
    actual_suppressed=${actual_suppressed:-0}
    if [[ "$actual_suppressed" -eq "$required_suppressed" ]]; then
      pass "$fixture_name run $run — suppressed count OK ($actual_suppressed)"
    else
      fail "$fixture_name run $run — suppressed: expected $required_suppressed, got $actual_suppressed"
    fi
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
static_shape_checks

if [[ "$MODE" == "live" ]]; then
  live_checks
  if [[ -n "$LOG_DIR" && -d "$LOG_DIR" ]]; then
    echo ""
    echo "=== Detection tally (fixture, code, tier, location, code-hits, code+location-hits, runs) ==="
    python3 "$TESTS_DIR/live_helpers.py" tally "$LOG_DIR" "$FIXTURES_DIR" || true
  fi
fi

echo ""
echo "=== Results ==="
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}All checks passed.${RESET}"
  exit 0
else
  echo -e "${RED}$FAILURES check(s) failed.${RESET}"
  exit 1
fi
