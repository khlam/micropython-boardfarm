#!/usr/bin/env bash
# Docker lint verifier shared by pre-commit and CI.
# Usage: run-linters.sh <file>...

set -uo pipefail

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

IMAGE_TAG_RUFF="local/ruff:latest"
IMAGE_TAG_VULTURE="local/vulture:latest"
IMAGE_TAG_PYDOCLINT="local/pydoclint:latest"
IMAGE_TAG_HADOLINT="local/hadolint:latest"
IMAGE_TAG_YAMLLINT="local/yamllint:latest"
IMAGE_TAG_TYPECHECK="local/typecheck:latest"
DOCKERFILE="Dockerfile.linters"
DOCKERFILE_TESTS="Dockerfile.tests"

_ensure_image() {
  local tag="$1" stage="$2" dockerfile="${3:-$DOCKERFILE}"
  if ! docker image inspect "$tag" >/dev/null 2>&1; then
    echo "[lint] Building $tag (one-time)..."
    docker build -q --target "$stage" -t "$tag" -f "$dockerfile" . >/dev/null
  fi
}

_ensure_image "$IMAGE_TAG_RUFF"      ruff-lint
_ensure_image "$IMAGE_TAG_VULTURE"   vulture-lint
_ensure_image "$IMAGE_TAG_PYDOCLINT" pydoclint-lint
_ensure_image "$IMAGE_TAG_HADOLINT"  hadolint-lint
_ensure_image "$IMAGE_TAG_YAMLLINT"  yamllint-lint

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

if (( ${#py_files[@]} > 0 )); then
  echo "[lint] ruff format --check (${#py_files[@]} file(s))"
  docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_RUFF" \
    format --check -- "${py_files[@]}" || fail=1

  echo "[lint] ruff check (${#py_files[@]} file(s))"
  docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_RUFF" \
    check --force-exclude -- "${py_files[@]}" || fail=1

  checked_py_files=()
  for f in "${py_files[@]}"; do
    case "$f" in
      firmware-packages/vl53l0x/vl53l0x/vl53l0x.py) continue ;;
      manifest.py) continue ;;
    esac
    checked_py_files+=("$f")
  done
  if (( ${#checked_py_files[@]} > 0 )); then
    echo "[lint] vulture (${#checked_py_files[@]} file(s))"
    docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_VULTURE" \
      --min-confidence 70 -- "${checked_py_files[@]}" .vulture_allowlist.py || fail=1

    echo "[lint] pydoclint (${#checked_py_files[@]} file(s))"
    docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_PYDOCLINT" \
      --style=google --allow-init-docstring=True -- "${checked_py_files[@]}" || fail=1
  fi

  _ensure_image "$IMAGE_TAG_TYPECHECK" typecheck "$DOCKERFILE_TESTS"
  echo "[lint] ty check"
  docker run --rm \
    -v "$PWD/firmware-packages":/work/firmware-packages:ro \
    -v "$PWD/cpython-packages":/work/cpython-packages:ro \
    -v "$PWD/projects":/work/projects:ro \
    "$IMAGE_TAG_TYPECHECK" || fail=1
fi

if (( ${#dockerfiles[@]} > 0 )); then
  for df in "${dockerfiles[@]}"; do
    echo "[lint] hadolint $df"
    docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_HADOLINT" \
      --failure-threshold error -c .hadolint.yaml "$df" || fail=1
  done
fi

if (( ${#yaml_files[@]} > 0 )); then
  for yf in "${yaml_files[@]}"; do
    echo "[lint] yamllint $yf"
    docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_YAMLLINT" \
      -c .yamllint.yaml "$yf" || fail=1
  done
fi

exit "$fail"
