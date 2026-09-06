// Build definitions for the build-only call sites: the lint/typecheck images
// (`make build-linters`) and the CVE-scan images (.github/workflows/ci.yml).
// Compose owns the *runtime* services — pytest, firmware compile, viz, uv —
// and supplies the wheels context itself via
// `additional_contexts: wheels: service:wheels`. Bake supplies the same context
// here via `contexts = { wheels = "target:wheels" }`, so the wheels build logic
// lives only once in Dockerfile.host (no mirrored stage in Dockerfile.tests).
//
// Usage:
//   docker buildx bake lint     # every linter + typecheck image
//   docker buildx bake scan     # every CVE-scan image
//   docker buildx bake ruff     # a single image, by target name

group "lint" {
  targets = ["ruff", "pydoclint", "vulture", "vulture-source", "hadolint", "yamllint", "typecheck"]
}

group "scan" {
  targets = ["scan-viz", "scan-pytest", "scan-uv-secure"]
}

// Internal-package wheels. Not built on its own — referenced as a build context
// by the targets that need /wheels, so bake builds it once per invocation and
// feeds it in. This is the single source of the wheel-build logic.
target "wheels" {
  dockerfile = "Dockerfile.host"
  target     = "wheels"
}

// ---------------------------------------------------------------------------
// Linter images — one tool each, tagged to match .githooks/run-linters.sh and
// the `make precommit` recipe.
// ---------------------------------------------------------------------------
target "ruff" {
  dockerfile = "Dockerfile.linters"
  target     = "ruff-lint"
  tags       = ["local/ruff:latest"]
}

target "pydoclint" {
  dockerfile = "Dockerfile.linters"
  target     = "pydoclint-lint"
  tags       = ["local/pydoclint:latest"]
}

target "vulture" {
  dockerfile = "Dockerfile.linters"
  target     = "vulture-lint"
  tags       = ["local/vulture:latest"]
}

// The same tool with the tests held out. A separate image because the pass
// needs its own confidence floor, exclusions, and pass/fail decision.
target "vulture-source" {
  dockerfile = "Dockerfile.linters"
  target     = "vulture-source-lint"
  tags       = ["local/vulture-source:latest"]
}

target "hadolint" {
  dockerfile = "Dockerfile.linters"
  target     = "hadolint-lint"
  tags       = ["local/hadolint:latest"]
}

target "yamllint" {
  dockerfile = "Dockerfile.linters"
  target     = "yamllint-lint"
  tags       = ["local/yamllint:latest"]
}

// ty over the workspace. Needs /wheels for `uv sync --frozen`, hence the context.
target "typecheck" {
  dockerfile = "Dockerfile.tests"
  target     = "typecheck"
  contexts   = { wheels = "target:wheels" }
  tags       = ["local/typecheck:latest"]
}

// ---------------------------------------------------------------------------
// CVE-scan images. Each is tagged local/scan:<name> for the Trivy step; the
// uv-secure image also carries local/uv-secure so the vuln-check job reuses it.
// ---------------------------------------------------------------------------
target "scan-viz" {
  dockerfile = "Dockerfile.host"
  target     = "viz"
  tags       = ["local/scan:viz"]
}

target "scan-pytest" {
  dockerfile = "Dockerfile.tests"
  target     = "pytest"
  contexts   = { wheels = "target:wheels" }
  tags       = ["local/scan:pytest"]
}

target "scan-uv-secure" {
  dockerfile = "Dockerfile.linters"
  target     = "uv-secure"
  tags       = ["local/uv-secure", "local/scan:uv-secure"]
}
