#!/usr/bin/env bash
# tsc gate (dev-only, so it lives beside plugin/, never inside it). Uses the
# engine-laid typings when the mod has been loaded once (.claude-plugin/types/ in
# plugin/ or in the harness folder), else a checked-in typings/claude-code.d.ts,
# else this build's typings from the plugin-authoring skill; with none it skips (exit 0) and says so. Covers plugin/ and its sibling tests/.
set -euo pipefail
mod="$(cd "$(dirname "$0")" && pwd)"
plugin="$mod/plugin"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
types=""
for d in "$plugin" "$mod"; do
  [ -f "$d/.claude-plugin/types/claude-code/index.d.ts" ] && { types="$d/.claude-plugin/types/claude-code/index.d.ts"; break; }
done
# 3. A checked-in copy, when the repo carries one (typings/claude-code.d.ts at the repo root).
if [ -z "$types" ] && [ -f "$mod/../../typings/claude-code.d.ts" ]; then
  types="$(cd "$mod/../.." && pwd)/typings/claude-code.d.ts"
fi
# 4. This build's typings from the plugin-authoring skill (macOS temp dir; absent on Linux and in CI).
if [ -z "$types" ]; then
  types=$(ls -t /private/tmp/claude-*/bundled-skills/*/*/plugin-authoring/types/claude-code.d.ts /tmp/claude-*/bundled-skills/*/*/plugin-authoring/types/claude-code.d.ts 2>/dev/null | head -1 || true)
fi
if [ -z "$types" ]; then
  # The engine writes its typings at load time and none is checked in here, so on a fresh checkout there is
  # nothing to check against. Say so loudly instead of failing a gate that cannot run; load the mod once
  # (or the plugin-authoring skill), or add typings/claude-code.d.ts, and it runs.
  echo "typecheck: SKIPPED — no claude-code typings found (none loaded, none in typings/, none from the plugin-authoring skill)." >&2
  exit 0
fi
cat > "$tmp/tsconfig.json" <<EOT
{ "compilerOptions": { "target": "es2023", "lib": ["es2023"], "types": [],
    "module": "esnext", "moduleResolution": "bundler", "strict": true,
    "noUncheckedIndexedAccess": true, "noEmit": true, "skipLibCheck": true,
    "jsx": "react", "jsxFactory": "h", "jsxFragmentFactory": "Fragment" },
  "include": ["$types", "$plugin/hooks", "$plugin/core", "$plugin/types", "$mod/tests"] }
EOT
tsc -p "$tmp/tsconfig.json"
