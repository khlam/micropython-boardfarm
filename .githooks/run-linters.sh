#!/usr/bin/env bash
# Single source of truth for Docker-based lint VERIFICATION.
#
# Called by both:
#   - .githooks/pre-commit         → after auto-fixers, on staged files
#   - .github/workflows/ci.yml     → on all tracked files
#
# Changes to ruff/vulture/hadolint/yamllint invocation here propagate to
# both. Auto-fixers (ruff format, ruff check --fix, yamlfix -i) live in
# pre-commit only — CI can't push fixes back and shouldn't silently rewrite
# code on behalf of a contributor.
#
# Usage: run-linters.sh <file>...
#
# Files are categorised by extension/name; each linter only runs over the
# files that match its category. Image builds are guarded so the first call
# pays the build cost and subsequent calls are instant.
#
# Exit 0 if all checks pass; non-zero on any lint failure (all linters run
# even if an earlier one fails, so a single invocation surfaces every
# issue).

set -uo pipefail

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

IMAGE_TAG_RUFF="local/ruff:latest"
IMAGE_TAG_VULTURE="local/vulture:latest"
IMAGE_TAG_HADOLINT="local/hadolint:latest"
IMAGE_TAG_YAMLLINT="local/yamllint:latest"
DOCKERFILE="Dockerfile.linters"

_ensure_image() {
  local tag="$1" stage="$2"
  if ! docker image inspect "$tag" >/dev/null 2>&1; then
    echo "[lint] Building $tag (one-time)..."
    docker build -q --target "$stage" -t "$tag" -f "$DOCKERFILE" . >/dev/null
  fi
}

_ensure_image "$IMAGE_TAG_RUFF"     ruff-lint
_ensure_image "$IMAGE_TAG_VULTURE"  vulture-lint
_ensure_image "$IMAGE_TAG_HADOLINT" hadolint-lint
_ensure_image "$IMAGE_TAG_YAMLLINT" yamllint-lint

# Categorise inputs by extension / filename. The Dockerfile pattern mirrors
# the pre-commit hook's original regex: `Dockerfile`, `Dockerfile.<suffix>`,
# or `*.dockerfile` (case-insensitive).
py_files=()
dockerfiles=()
yaml_files=()
for f in "$@"; do
  case "$f" in
    *.py)
      py_files+=("$f")
      ;;
  esac
  case "$f" in
    Dockerfile|Dockerfile.*|*/Dockerfile|*/Dockerfile.*|*.dockerfile|*.Dockerfile)
      dockerfiles+=("$f")
      ;;
  esac
  case "$f" in
    *.yml|*.yaml|*.YML|*.YAML)
      yaml_files+=("$f")
      ;;
  esac
done

fail=0

# --- Ruff: format check + lint check (no fixes) ---
if (( ${#py_files[@]} > 0 )); then
  echo "[lint] ruff format --check (${#py_files[@]} file(s))"
  docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_RUFF" \
    format --check -- "${py_files[@]}" || fail=1

  echo "[lint] ruff check (${#py_files[@]} file(s))"
  docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_RUFF" \
    check --force-exclude -- "${py_files[@]}" || fail=1

  # Vulture: skip the vendored VL53L0X driver and manifest.py (both also
  # excluded from ruff in pyproject.toml). Allowlist is always appended.
  vulture_files=()
  for f in "${py_files[@]}"; do
    case "$f" in
      firmware-packages/vl53l0x/vl53l0x/vl53l0x.py) continue ;;
      manifest.py) continue ;;
    esac
    vulture_files+=("$f")
  done
  if (( ${#vulture_files[@]} > 0 )); then
    echo "[lint] vulture (${#vulture_files[@]} file(s))"
    docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_VULTURE" \
      --min-confidence 70 -- "${vulture_files[@]}" .vulture_allowlist.py || fail=1
  fi
fi

# --- Hadolint: one container per Dockerfile (matches pre-commit) ---
if (( ${#dockerfiles[@]} > 0 )); then
  for df in "${dockerfiles[@]}"; do
    echo "[lint] hadolint $df"
    docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_HADOLINT" \
      --failure-threshold error -c .hadolint.yaml "$df" || fail=1
  done
fi

# --- Yamllint: one container per YAML file (matches pre-commit) ---
if (( ${#yaml_files[@]} > 0 )); then
  for yf in "${yaml_files[@]}"; do
    echo "[lint] yamllint $yf"
    docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_YAMLLINT" \
      -c .yamllint.yaml "$yf" || fail=1
  done
fi

exit "$fail"
