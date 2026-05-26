#!/usr/bin/env bash
# Enforces semantic versioning on the workspace: if a package's or
# project's code changes, that scope's pyproject.toml version must bump
# in the same commit. Pure git/bash — no Docker needed.
#
# Scopes (each staged file lands in its most-specific scope; no double-
# counting):
#   firmware-packages/<pkg>/    → firmware-packages/<pkg>/pyproject.toml
#   cpython-packages/<pkg>/     → cpython-packages/<pkg>/pyproject.toml
#   projects/<name>/            → projects/<name>/pyproject.toml
#   <repo root>                 → pyproject.toml  (everything else)
#
# Trigger files: *.py, *.toml, *.yaml, *.yml, Dockerfile*. Docs (*.md),
# the uv.lock, anything under outputs/, and the scope's own
# pyproject.toml don't trigger a version bump.
#
# Newly-added pyproject.toml files are exempt (no HEAD version to
# compare against).

set -euo pipefail

# Collect staged additions/copies/modifications/renames.
mapfile -d '' -t staged_files < <(git diff --cached --name-only --diff-filter=ACMR -z)
(( ${#staged_files[@]} == 0 )) && exit 0

# Build list of versionable scopes: "<pyproject>::<dir>". Order doesn't
# matter; longest-prefix wins below.
scopes=("pyproject.toml::")
for d in firmware-packages/*/ cpython-packages/*/ projects/*/; do
  [[ -f "${d}pyproject.toml" ]] && scopes+=("${d}pyproject.toml::${d}")
done

# Map: scope-pyproject path → 1 if it has staged trigger files in scope.
declare -A scope_dirty=()

for f in "${staged_files[@]}"; do
  # Skip non-trigger files.
  case "$f" in
    *.md|uv.lock|*/outputs/*|*.uf2|*.bin) continue ;;
  esac
  case "$f" in
    *.py|*.toml|*.yaml|*.yml) ;;
    Dockerfile*|*/Dockerfile*) ;;
    *) continue ;;
  esac

  # Find most-specific scope (longest dir prefix). Root scope's empty
  # dir matches everything as a fallback.
  best_pp="pyproject.toml"
  best_len=0
  for s in "${scopes[@]}"; do
    pp="${s%%::*}"
    dir="${s##*::}"
    [[ -z "$dir" ]] && continue
    if [[ "$f" == "$dir"* ]]; then
      len=${#dir}
      if (( len > best_len )); then
        best_pp="$pp"
        best_len=$len
      fi
    fi
  done

  # A pyproject change shouldn't trigger its own scope (the version bump
  # itself is what we're verifying lives there).
  [[ "$f" == "$best_pp" ]] && continue

  scope_dirty["$best_pp"]=1
done

# Verify: each dirty scope's version must differ between HEAD and staged.
failed=0
for pp in "${!scope_dirty[@]}"; do
  staged_ver=$(git show ":${pp}" 2>/dev/null \
    | awk -F'"' '/^version = /{print $2; exit}')
  head_ver=$(git show "HEAD:${pp}" 2>/dev/null \
    | awk -F'"' '/^version = /{print $2; exit}' || true)

  # New pyproject (no HEAD): exempt.
  [[ -z "$head_ver" ]] && continue

  if [[ -z "$staged_ver" ]]; then
    echo "[pre-commit] ${pp}: could not parse 'version = \"...\"' from staged file"
    failed=1
    continue
  fi

  if [[ "$staged_ver" == "$head_ver" ]]; then
    echo "[pre-commit] ${pp}: version is still ${staged_ver}, but staged code changes exist in its scope"
    failed=1
  fi
done

if (( failed != 0 )); then
  echo
  echo "[pre-commit] Bump the version in the listed pyproject.toml file(s) before committing."
  echo "[pre-commit] (Or run \`git commit --no-verify\` to skip — discouraged.)"
  exit 1
fi

exit 0
