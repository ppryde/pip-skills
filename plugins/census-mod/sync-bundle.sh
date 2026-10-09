#!/usr/bin/env bash
# Copy the census Python that census-mod bundles (plugin/scripts/) from its one source, plugins/census/scripts/.
# census-mod is a standalone plugin: it records through its OWN copy of census's ingest and reads through its own
# vitals, never through the census plugin. The copies are byte-identical; tests/census/test_census_mod_bundle.py
# fails when they drift, and this script is the fix:  plugins/census-mod/sync-bundle.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
src="$here/../census/scripts"
dest="$here/plugin/scripts"
# __init__ (the package), the CLI (ingest, read, where), the store and what it needs, vitals. NOT install, render
# or statusline: the command status line is the census plugin's job, not census-mod's.
FILES=(__init__.py cli.py gitcache.py resolve.py store.py vitals.py where.py)
mkdir -p "$dest"
for f in "${FILES[@]}"; do cp "$src/$f" "$dest/$f"; done
# nothing else may linger from an earlier bundle
for f in "$dest"/*.py; do
  keep=0
  for g in "${FILES[@]}"; do [ "$(basename "$f")" = "$g" ] && keep=1; done
  [ "$keep" = 1 ] || rm -f "$f"
done
echo "census-mod bundle synced: ${FILES[*]}"
