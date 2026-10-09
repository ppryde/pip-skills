#!/usr/bin/env bash
# tsc gate (dev-only, so it lives beside plugin/, never inside it). Uses the
# engine-laid typings when the mod has been loaded once (.claude-plugin/types/ in
# plugin/ or in the harness folder), else this build's typings from the
# plugin-authoring skill. Covers plugin/ and its sibling tests/.
set -euo pipefail
mod="$(cd "$(dirname "$0")" && pwd)"
plugin="$mod/plugin"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
types=""
for d in "$plugin" "$mod"; do
  [ -f "$d/.claude-plugin/types/claude-code/index.d.ts" ] && { types="$d/.claude-plugin/types/claude-code/index.d.ts"; break; }
done
if [ -z "$types" ]; then
  types=$(ls -t /private/tmp/claude-*/bundled-skills/*/*/plugin-authoring/types/claude-code.d.ts 2>/dev/null | head -1 || true)
fi
if [ -z "$types" ]; then
  echo "typecheck: no claude-code typings — load the plugin-authoring skill (or this mod) once" >&2
  exit 2
fi
cat > "$tmp/tsconfig.json" <<EOT
{ "compilerOptions": { "target": "es2023", "lib": ["es2023"], "types": [],
    "module": "esnext", "moduleResolution": "bundler", "strict": true,
    "noUncheckedIndexedAccess": true, "noEmit": true, "skipLibCheck": true,
    "jsx": "react", "jsxFactory": "h", "jsxFragmentFactory": "Fragment" },
  "include": ["$types", "$plugin/hooks", "$plugin/core", "$plugin/types", "$mod/tests"] }
EOT
tsc -p "$tmp/tsconfig.json"
