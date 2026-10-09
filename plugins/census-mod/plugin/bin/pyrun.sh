#!/bin/sh
# pyrun.sh SCRIPT [ARGS...]: run a Python script with the first launcher that works (python3, python, py -3), saying
# nothing about the ones that do not, so a command's captured output is the script's alone.
script=$1
shift
for py in python3 python; do
  # `-c ''` also rules out the Windows Store stub, which is on PATH but only opens the Store
  if command -v "$py" >/dev/null 2>&1 && "$py" -c '' >/dev/null 2>&1; then exec "$py" "$script" "$@"; fi
done
if command -v py >/dev/null 2>&1 && py -3 -c '' >/dev/null 2>&1; then exec py -3 "$script" "$@"; fi
echo "census-mod: no Python found (tried python3, python, py -3)" >&2
exit 127
