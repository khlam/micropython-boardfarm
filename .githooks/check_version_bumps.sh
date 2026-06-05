#!/usr/bin/env bash
# Require a version bump when code/config changes inside a versioned scope.
#
# A "scope" is a directory holding a pyproject.toml: the repo root, plus every
# firmware-packages/*/, cpython-packages/*/, and projects/*/ that has one.
# A changed source file dirties its nearest enclosing scope, and any dirty
# scope must also change its `version = "..."` line, or this check fails.
#
# Usage:
#   check_version_bumps.sh             pre-commit: staged index vs HEAD
#   check_version_bumps.sh --base REF  CI: working tree vs REF (e.g. origin/main)
set -euo pipefail

_parse_version() { awk -F'"' '/^version = /{print $2; exit}'; }  # stdin -> version

# Mode picks the label, the changed-path listing, and where "new"/"old"
# pyproject contents are read from.
if [[ "${1:-}" == "--base" ]]; then
  base_ref="${2:-}"
  [[ -n "$base_ref" ]] || { echo "usage: $0 [--base <ref>]" >&2; exit 2; }
  label="ci"
  old_ref="$base_ref"
  list_changed() { git diff --name-only --diff-filter=ACMR -z "$base_ref...HEAD"; }
  new_version()  { [[ -f "$1" ]] && _parse_version <"$1"; return 0; }
else
  label="pre-commit"
  old_ref="HEAD"
  list_changed() { git diff --cached --name-only --diff-filter=ACMR -z; }
  new_version()  { git show ":$1" 2>/dev/null | _parse_version; }
fi
old_version() { git show "$old_ref:$1" 2>/dev/null | _parse_version; }

mapfile -d '' -t files < <(list_changed)
(( ${#files[@]} )) || exit 0

# Scope directories that actually carry a pyproject.toml (root is the default).
scope_dirs=()
for d in firmware-packages/*/ cpython-packages/*/ projects/*/; do
  [[ -f "${d}pyproject.toml" ]] && scope_dirs+=("$d")
done

# Map each relevant changed file to the pyproject.toml of its nearest scope.
declare -A dirty=()
for f in "${files[@]}"; do
  case "$f" in
    *.md|uv.lock|*/outputs/*|*.uf2|*.bin) continue ;;       # never a bump trigger
    *.py|*.toml|*.yaml|*.yml|Dockerfile*|*/Dockerfile*) ;;  # source/config: counts
    *) continue ;;
  esac

  pp="pyproject.toml"
  for d in "${scope_dirs[@]}"; do
    [[ "$f" == "$d"* ]] && { pp="${d}pyproject.toml"; break; }
  done

  # Editing a pyproject.toml does not, by itself, dirty its own scope.
  [[ "$f" == "$pp" ]] || dirty["$pp"]=1
done

# A dirty scope must show a changed version against the comparison ref.
failed=0
for pp in "${!dirty[@]}"; do
  old_ver=$(old_version "$pp") || true
  [[ -n "$old_ver" ]] || continue   # brand-new scope: nothing to compare

  new_ver=$(new_version "$pp") || true
  if [[ -z "$new_ver" ]]; then
    echo "[$label] $pp: could not parse 'version = \"...\"'"
    failed=1
  elif [[ "$new_ver" == "$old_ver" ]]; then
    echo "[$label] $pp: version is still $new_ver, but code changes exist in its scope"
    failed=1
  fi
done

(( failed )) || exit 0

echo
echo "[$label] Bump the version in the listed pyproject.toml file(s)."
if [[ "$label" == "pre-commit" ]]; then
  echo "[$label] (Or run \`git commit --no-verify\` to skip — discouraged.)"
fi
exit 1
