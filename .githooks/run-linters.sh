#!/usr/bin/env bash
# Docker lint verifier for CI. Routes each file to the appropriate linter(s)
# based on its type: ruff + vulture + pydoclint + ty on Python, hadolint on
# Dockerfiles, yamllint on YAML.
# Usage: run-linters.sh <file>...
#
# The local pre-commit runs a faster subset (no vulture) via `make precommit`;
# this script is the comprehensive gate invoked by .github/workflows/ci.yml.

# -e omitted intentionally: fail=1 accumulates tool failures without early exit.
set -uo pipefail

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

IMAGE_TAG_RUFF="local/ruff:latest"
IMAGE_TAG_VULTURE="local/vulture:latest"
IMAGE_TAG_PYDOCLINT="local/pydoclint:latest"
IMAGE_TAG_HADOLINT="local/hadolint:latest"
IMAGE_TAG_YAMLLINT="local/yamllint:latest"
IMAGE_TAG_TYPECHECK="local/typecheck:latest"

# Images are built by docker buildx bake (docker-bake.hcl), which also wires the
# wheels build context into the typecheck image. buildkit caches across runs, so
# re-baking an unchanged target is cheap. The tags above match the bake targets.
bake=(docker buildx bake -f docker-bake.hcl)

# Bucket each input file by type so each linter only receives the files it understands.
py_files=()
dockerfiles=()
yaml_files=()
for f in "$@"; do
  case "$f" in
    *.py)                                                                   py_files+=("$f") ;;
    Dockerfile|Dockerfile.*|*/Dockerfile|*/Dockerfile.*|*.dockerfile|*.Dockerfile) dockerfiles+=("$f") ;;
    *.yml|*.yaml)                                                           yaml_files+=("$f") ;;
  esac
done

# Accumulate failures so every linter runs even when an earlier one fails.
fail=0

if (( ${#py_files[@]} > 0 )); then
  "${bake[@]}" ruff pydoclint vulture typecheck || fail=1

  echo "[lint] ruff format --check (${#py_files[@]} file(s))"
  docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_RUFF" \
    format --check -- "${py_files[@]}" || fail=1

  echo "[lint] ruff check (${#py_files[@]} file(s))"
  docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_RUFF" \
    check --force-exclude -- "${py_files[@]}" || fail=1

  echo "[lint] vulture (${#py_files[@]} file(s))"
  docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_VULTURE" \
    -- "${py_files[@]}" .vulture_allowlist.py || fail=1

  echo "[lint] pydoclint (${#py_files[@]} file(s))"
  docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_PYDOCLINT" \
    --style=google --allow-init-docstring=True -- "${py_files[@]}" || fail=1

  # ty type-checks the whole source tree, not just the changed files,
  # so it always runs once rather than per-file.
  echo "[lint] ty check"
  docker run --rm \
    -v "$PWD/firmware-packages":/work/firmware-packages:ro \
    -v "$PWD/cpython-packages":/work/cpython-packages:ro \
    -v "$PWD/projects":/work/projects:ro \
    "$IMAGE_TAG_TYPECHECK" || fail=1
fi

# Lint each Dockerfile for best-practice errors; warnings are informational only.
if (( ${#dockerfiles[@]} > 0 )); then
  "${bake[@]}" hadolint || fail=1
  for df in "${dockerfiles[@]}"; do
    echo "[lint] hadolint $df"
    docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_HADOLINT" \
      --failure-threshold error -c .hadolint.yaml "$df" || fail=1
  done
fi

# Lint each YAML file for syntax and style conformance.
if (( ${#yaml_files[@]} > 0 )); then
  "${bake[@]}" yamllint || fail=1
  for yf in "${yaml_files[@]}"; do
    echo "[lint] yamllint $yf"
    docker run --rm -v "$PWD":/work -w /work "$IMAGE_TAG_YAMLLINT" \
      -c .yamllint.yaml "$yf" || fail=1
  done
fi

exit "$fail"
