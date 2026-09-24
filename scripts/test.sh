#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
python3 -m pytest "$@"
while IFS= read -r -d '' file; do bash -n "$file"; done < <(find scripts image -name '*.sh' -print0)
python3 -m compileall -q src scripts image
