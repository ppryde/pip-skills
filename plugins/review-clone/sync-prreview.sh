#!/usr/bin/env bash
# Refresh review-clone's vendored copy of review-panel's inline-posting CLI.
# Canonical: plugins/review-panel/scripts/prreview.py. The copy must stay
# byte-identical; tests/review-clone/test_prreview_sync.py fails on drift.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
src="$here/../review-panel/scripts/prreview.py"
dst="$here/scripts/prreview.py"
cp "$src" "$dst"
echo "synced $dst"
