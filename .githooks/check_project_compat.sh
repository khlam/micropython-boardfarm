#!/usr/bin/env bash
# Verifies each project's declared `micropython-boardfarm>=X.Y.Z` floor
# is satisfied by the root pyproject's `version`. Invoked from the
# pre-commit hook AND from the rp / esp32 (Dockerfile.firmware) and
# pytest (Dockerfile.tests) ENTRYPOINTs — same script, three entry
# points, one source of truth.
#
# Usage: check_project_compat.sh <root_pyproject> <project_pyproject>...
#
# Exit 0 if every project floor is satisfied; exit 1 on mismatch; exit 2
# if the root pyproject is unparseable.

set -euo pipefail

if (( $# < 2 )); then
  echo "usage: $0 <root_pyproject> <project_pyproject>..." >&2
  exit 2
fi

root_pp="$1"; shift
root_ver=$(awk -F'"' '/^version = /{print $2; exit}' "$root_pp")
if [[ -z "$root_ver" ]]; then
  echo "[compat] could not parse version from $root_pp" >&2
  exit 2
fi

failed=0
for proj_pp in "$@"; do
  [[ -f "$proj_pp" ]] || continue
  floor=$(grep -oE 'micropython-boardfarm>=[0-9]+\.[0-9]+\.[0-9]+' "$proj_pp" \
            | head -1 | sed 's/.*>=//')
  if [[ -z "$floor" ]]; then
    echo "[compat] $proj_pp: no micropython-boardfarm pin found — skipping" >&2
    continue
  fi
  # sort -V is GNU version-sort, present in every base image we use
  # (Ubuntu 24.04, espressif/idf 5.5.1, python:3.13-slim). If the floor
  # sorts first, root_ver >= floor → compatible.
  if [[ "$(printf '%s\n%s\n' "$floor" "$root_ver" | sort -V | head -1)" != "$floor" ]]; then
    echo "[compat] $proj_pp requires micropython-boardfarm>=$floor but root is $root_ver" >&2
    failed=1
  fi
done

if (( failed != 0 )); then
  echo >&2
  echo "[compat] Bump the project's pin (or root version) before building." >&2
  exit 1
fi

exit 0
