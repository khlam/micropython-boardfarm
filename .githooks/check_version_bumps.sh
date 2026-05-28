#!/usr/bin/env bash
# Require a version bump when code/config changes inside a versioned scope.
# Modes: staged index vs HEAD, or --base <ref> for CI.
# todo: refactor and make this readable and much smaller
set -euo pipefail

mode="staged"
base_ref=""
label="pre-commit"
if [[ "${1:-}" == "--base" ]]; then
  if [[ -z "${2:-}" ]]; then
    echo "usage: $0 [--base <ref>]" >&2
    exit 2
  fi
  mode="base"
  base_ref="$2"
  label="ci"
fi

_new_version() {
  local pp="$1"
  if [[ "$mode" == "base" ]]; then
    [[ -f "$pp" ]] || return 0
    awk -F'"' '/^version = /{print $2; exit}' "$pp"
  else
    git show ":${pp}" 2>/dev/null | awk -F'"' '/^version = /{print $2; exit}'
  fi
}

_old_version() {
  local pp="$1" ref
  ref=$([[ "$mode" == "base" ]] && echo "$base_ref" || echo "HEAD")
  git show "${ref}:${pp}" 2>/dev/null | awk -F'"' '/^version = /{print $2; exit}' || true
}

if [[ "$mode" == "base" ]]; then
  mapfile -d '' -t changed_files < <(
    git diff --name-only --diff-filter=ACMR -z "${base_ref}...HEAD")
else
  mapfile -d '' -t changed_files < <(
    git diff --cached --name-only --diff-filter=ACMR -z)
fi
(( ${#changed_files[@]} == 0 )) && exit 0

scopes=("pyproject.toml::")
for d in firmware-packages/*/ cpython-packages/*/ projects/*/; do
  [[ -f "${d}pyproject.toml" ]] && scopes+=("${d}pyproject.toml::${d}")
done

declare -A scope_dirty=()

for f in "${changed_files[@]}"; do
  case "$f" in
    *.md|uv.lock|*/outputs/*|*.uf2|*.bin) continue ;;
  esac
  case "$f" in
    *.py|*.toml|*.yaml|*.yml) ;;
    Dockerfile*|*/Dockerfile*) ;;
    *) continue ;;
  esac

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

  [[ "$f" == "$best_pp" ]] && continue

  scope_dirty["$best_pp"]=1
done

failed=0
for pp in "${!scope_dirty[@]}"; do
  new_ver=$(_new_version "$pp")
  old_ver=$(_old_version "$pp")

  [[ -z "$old_ver" ]] && continue

  if [[ -z "$new_ver" ]]; then
    echo "[${label}] ${pp}: could not parse 'version = \"...\"'"
    failed=1
    continue
  fi

  if [[ "$new_ver" == "$old_ver" ]]; then
    echo "[${label}] ${pp}: version is still ${new_ver}, but code changes exist in its scope"
    failed=1
  fi
done

if (( failed != 0 )); then
  echo
  echo "[${label}] Bump the version in the listed pyproject.toml file(s)."
  if [[ "$mode" == "staged" ]]; then
    echo "[${label}] (Or run \`git commit --no-verify\` to skip — discouraged.)"
  fi
  exit 1
fi

exit 0
