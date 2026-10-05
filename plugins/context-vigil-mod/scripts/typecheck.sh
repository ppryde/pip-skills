#!/usr/bin/env bash
# tsc gate. Uses the engine-laid typings when the mod has been loaded once
# (.claude-plugin/types/), else this build's typings from the plugin-authoring skill.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .claude-plugin/types/claude-code/index.d.ts ]; then exec tsc -p .; fi
types=$(ls -t /private/tmp/claude-*/bundled-skills/*/*/plugin-authoring/types/claude-code.d.ts 2>/dev/null | head -1 || true)
if [ -z "$types" ]; then
  echo "typecheck: no claude-code typings — load the plugin-authoring skill (or this mod) once" >&2
  exit 2
fi
tmp=$(mktemp -d)
here=$(pwd)
cat > "$tmp/tsconfig.json" <<EOT
{ "compilerOptions": { "target": "es2023", "lib": ["es2023"], "types": [],
    "module": "esnext", "moduleResolution": "bundler", "strict": true,
    "noUncheckedIndexedAccess": true, "noEmit": true, "skipLibCheck": true,
    "jsx": "react", "jsxFactory": "h", "jsxFragmentFactory": "Fragment" },
  "include": ["$types", "$here/hooks", "$here/core", "$here/types", "$here/tests"] }
EOT
exec tsc -p "$tmp/tsconfig.json"
