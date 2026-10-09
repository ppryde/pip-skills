#!/usr/bin/env bash
# tsc gate. Uses the engine-laid typings when the mod has been loaded once
# (.claude-plugin/types/), else this build's typings from the plugin-authoring skill.
set -euo pipefail
cd "$(dirname "$0")/.."
# The mod's tests live outside the plugin (repo tests/census_mod/), so
# the plugin's own tsconfig.json cannot see them: both branches add them here.
here=$(pwd)
tests="$(cd "$here/../../tests/census_mod" && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
if [ -f .claude-plugin/types/claude-code/index.d.ts ]; then
  cat > "$tmp/tsconfig.json" <<EOT
{ "extends": "$here/tsconfig.json",
  "include": ["$here/.claude-plugin/types/claude-code/index.d.ts", "$here/hooks", "$here/core", "$here/types", "$tests"] }
EOT
  tsc -p "$tmp/tsconfig.json"; exit $?
fi
types=$(ls -t /private/tmp/claude-*/bundled-skills/*/*/plugin-authoring/types/claude-code.d.ts 2>/dev/null | head -1 || true)
if [ -z "$types" ]; then
  echo "typecheck: no claude-code typings — load the plugin-authoring skill (or this mod) once" >&2
  exit 2
fi
cat > "$tmp/tsconfig.json" <<EOT
{ "compilerOptions": { "target": "es2023", "lib": ["es2023"], "types": [],
    "module": "esnext", "moduleResolution": "bundler", "strict": true,
    "noUncheckedIndexedAccess": true, "noEmit": true, "skipLibCheck": true,
    "jsx": "react", "jsxFactory": "h", "jsxFragmentFactory": "Fragment" },
  "include": ["$types", "$here/hooks", "$here/core", "$here/types", "$tests"] }
EOT
tsc -p "$tmp/tsconfig.json"
