#!/usr/bin/env bash
# Test harness for django-inquisition:optimise-orm
# Modes:
#   (no args)   — static-shape validation only (fast, CI-safe)
#   --live      — live invocation against all fixtures (requires API key + Claude CLI)
#   --fixture N — live invocation against a single fixture by number (e.g. --fixture 01)
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
    --help|-h)
      sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# //'
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

  # --- 4. SKILL.md references all 8 check-group files ---
  for group in "${EXPECTED_GROUPS[@]}"; do
    if grep -q "checks/${group}\.md" "$SKILL_DIR/SKILL.md"; then
      pass "SKILL.md references checks/$group.md"
    else
      fail "SKILL.md does not reference checks/$group.md"
    fi
  done

  # --- 5. SKILL.md references all expected check codes ---
  # Codes extracted from the quick-reference table in SKILL.md
  EXPECTED_CODES=(
    FETCH-001 FETCH-002 FETCH-003 FETCH-010 FETCH-011 FETCH-012
    FETCH-020 FETCH-021 FETCH-022 FETCH-030 FETCH-031 FETCH-032
    CARD-001 CARD-002 CARD-003 CARD-010 CARD-011 CARD-020 CARD-021
    AGG-001 AGG-002 AGG-010 AGG-011 AGG-020 AGG-030 AGG-031 AGG-040
    WRITE-001 WRITE-002 WRITE-003 WRITE-004 WRITE-005 WRITE-006 WRITE-007
    WRITE-008 WRITE-009 WRITE-010 WRITE-020 WRITE-030 WRITE-031 WRITE-040
    ITER-001 ITER-002 ITER-010 ITER-011
    IDX-001 IDX-002 IDX-010 IDX-011 IDX-020 IDX-030 IDX-040 IDX-041 IDX-050 IDX-060 IDX-061
    JOIN-001 JOIN-002 JOIN-010 JOIN-011
    PAT-001 PAT-002 PAT-003 PAT-010 PAT-011 PAT-020 PAT-030 PAT-040 PAT-050 PAT-060 PAT-061 PAT-070
  )

  for code in "${EXPECTED_CODES[@]}"; do
    if grep -q "$code" "$SKILL_DIR/SKILL.md"; then
      pass "SKILL.md references $code"
    else
      fail "SKILL.md missing code reference: $code"
    fi
  done

  # --- 6. Severity mapping rules are present in SKILL.md ---
  SEVERITY_PATTERNS=(
    "critical" "savings_midpoint" "confidence_weight" "sort_key"
    "header banner" "noqa: optimise-orm"
  )
  for pattern in "${SEVERITY_PATTERNS[@]}"; do
    if grep -q "$pattern" "$SKILL_DIR/SKILL.md"; then
      pass "SKILL.md contains ranking concept: $pattern"
    else
      fail "SKILL.md missing ranking concept: $pattern"
    fi
  done

  # --- 7. Each check file lists its codes in frontmatter ---
  # NOTE: bash 3.2 (macOS default) lacks associative arrays, so we use a function
  # with a case lookup. Keep the lists aligned with the design spec §4.
  codes_for_group() {
    case "$1" in
      fetching)    echo "FETCH-001 FETCH-002 FETCH-003 FETCH-010 FETCH-011 FETCH-012 FETCH-020 FETCH-021 FETCH-022 FETCH-030 FETCH-031 FETCH-032" ;;
      cardinality) echo "CARD-001 CARD-002 CARD-003 CARD-010 CARD-011 CARD-020 CARD-021" ;;
      aggregation) echo "AGG-001 AGG-002 AGG-010 AGG-011 AGG-020 AGG-030 AGG-031 AGG-040" ;;
      writes)      echo "WRITE-001 WRITE-002 WRITE-003 WRITE-004 WRITE-005 WRITE-006 WRITE-007 WRITE-008 WRITE-009 WRITE-010 WRITE-020 WRITE-030 WRITE-031 WRITE-040" ;;
      iteration)   echo "ITER-001 ITER-002 ITER-010 ITER-011" ;;
      indexes)     echo "IDX-001 IDX-002 IDX-010 IDX-011 IDX-020 IDX-030 IDX-040 IDX-041 IDX-050 IDX-060 IDX-061" ;;
      joins)       echo "JOIN-001 JOIN-002 JOIN-010 JOIN-011" ;;
      patterns)    echo "PAT-001 PAT-002 PAT-003 PAT-010 PAT-011 PAT-020 PAT-030 PAT-040 PAT-050 PAT-060 PAT-061 PAT-070" ;;
    esac
  }

  for group in "${EXPECTED_GROUPS[@]}"; do
    local file="$CHECKS_DIR/$group.md"
    [[ -f "$file" ]] || continue
    for code in $(codes_for_group "$group"); do
      if grep -q "$code" "$file"; then
        pass "checks/$group.md contains $code"
      else
        fail "checks/$group.md missing $code"
      fi
    done
  done

  # --- 8. Fixture directories exist (structure check only) ---
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

  # --- 9. Each present fixture has target.py and expected.json ---
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
  if ! command -v claude &>/dev/null; then
    echo "ERROR: 'claude' CLI not found. Live mode requires Claude Code CLI." >&2
    exit 2
  fi

  # python3 is required for expected.json parsing — fail loudly if missing.
  if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required for live mode (expected.json parsing)" >&2
    exit 2
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

    local target_path="$fixture_dir/target.py"
    local expected_path="$fixture_dir/expected.json"
    local report_path stderr_path
    report_path=$(mktemp "/tmp/optimise-orm-live-XXXXXX.md")
    stderr_path=$(mktemp /tmp/optimise-orm-stderr-XXXXXX)

    # Invoke skill with --report so we can parse frontmatter. Use `claude -p`
    # (the documented headless mode) and redirect stdout to capture the report.
    echo "  Running: claude -p '/django-inquisition:optimise-orm $target_path --report --no-explain'"
    if ! claude -p "/django-inquisition:optimise-orm $target_path --report --no-explain" \
         >"$report_path" 2>"$stderr_path"; then
      fail "$fixture_name — skill invocation failed (stderr: $stderr_path)"
      cat "$stderr_path" >&2
      rm -f "$report_path" "$stderr_path"
      continue
    fi
    rm -f "$stderr_path"

    # Parse report frontmatter findings_count
    local actual_critical actual_medium actual_low
    actual_critical=$(grep 'critical:' "$report_path" | head -1 | grep -o '[0-9]*' || echo 0)
    actual_medium=$(grep 'medium:' "$report_path" | head -1 | grep -o '[0-9]*' || echo 0)
    actual_low=$(grep 'low:' "$report_path" | head -1 | grep -o '[0-9]*' || echo 0)

    # Parse expected.json once: emit `<critical> <medium> <low>` on line 1
    # then one `<id>|<location_pattern>` per finding. Single python3 invocation
    # replaces four separate parse attempts.
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
      rm -f "$report_path"
      exit 2
    fi

    local required_critical required_medium required_low required_pairs
    required_critical=$(echo "$parsed" | sed -n '1p' | awk '{print $1}')
    required_medium=$(echo "$parsed" | sed -n '1p' | awk '{print $2}')
    required_low=$(echo "$parsed" | sed -n '1p' | awk '{print $3}')
    required_pairs=$(echo "$parsed" | sed -n '2,$p')

    # Check critical findings (zero variance allowed per spec §7.3)
    if [[ "$actual_critical" -lt "$required_critical" ]]; then
      fail "$fixture_name — critical findings: expected ≥$required_critical, got $actual_critical"
    else
      pass "$fixture_name — critical findings count OK ($actual_critical)"
    fi

    # Check medium findings (≥80% threshold per spec §7.3)
    local medium_threshold=$(( required_medium * 80 / 100 ))
    if [[ "$required_medium" -gt 0 && "$actual_medium" -lt "$medium_threshold" ]]; then
      fail "$fixture_name — medium findings: expected ≥${medium_threshold} (80% of $required_medium), got $actual_medium"
    elif [[ "$required_medium" -gt 0 ]]; then
      pass "$fixture_name — medium findings count OK ($actual_medium / $required_medium)"
    fi

    # Low findings — informational only, not enforced
    if [[ "$required_low" -gt 0 ]]; then
      echo "  INFO: $fixture_name — low findings: $actual_low (required $required_low, not enforced)"
    fi

    # Check each required (id, location_pattern) pair appears in the report.
    while IFS='|' read -r code loc_pattern; do
      [[ -z "$code" ]] && continue
      if grep -q "$code" "$report_path" && grep -q "$loc_pattern" "$report_path"; then
        pass "$fixture_name — required finding $code @ $loc_pattern present"
      else
        fail "$fixture_name — required finding $code @ $loc_pattern NOT found in report"
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
    data = json.load(open('$meta_path'))
except Exception as e:
    print(f'PARSE_ERROR: {e}', file=sys.stderr)
    sys.exit(1)
print(data.get('suppressed_count', 0))
" 2>&1); then
        echo "ERROR: failed to parse $meta_path: $required_suppressed" >&2
        rm -f "$report_path"
        exit 2
      fi
      actual_suppressed=$(grep -E '^suppressed:[[:space:]]*[0-9]+' "$report_path" | head -1 | grep -oE '[0-9]+' || echo 0)
      if [[ "$actual_suppressed" -eq "$required_suppressed" ]]; then
        pass "$fixture_name — suppressed count OK ($actual_suppressed)"
      else
        fail "$fixture_name — suppressed: expected $required_suppressed, got $actual_suppressed"
      fi
    fi

    rm -f "$report_path"
  done
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
static_shape_checks

if [[ "$MODE" == "live" ]]; then
  live_checks
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
