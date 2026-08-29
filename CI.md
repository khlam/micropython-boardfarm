# CI & Local Checks

How quality gates are wired in this repo: a fast **local pre-commit** gate driven
by the [`Makefile`](Makefile), and a comprehensive **GitHub Actions CI** pipeline in
[.github/workflows/ci.yml](.github/workflows/ci.yml). Everything runs inside Docker —
there is no host toolchain to install (see [AGENTS.md](AGENTS.md) "Host policy").

The two surfaces share the same linter images and configs, so a check that passes
locally behaves the same in CI. The local hook deliberately runs a faster subset;
the heavier, repo-wide gates run only in CI.

## Makefile targets

| Target | Purpose |
|---|---|
| `make init` | Point git's `core.hooksPath` at [.githooks/](.githooks/) and make the `pre-commit` hook executable. Run once after cloning. |
| `make precommit` | The self-contained local gate. Auto-fixes staged Python in place (`ruff format`, `ruff check --fix`, then re-stages), then verifies `ruff` + `pydoclint` + `ty`. Invoked automatically by the `.githooks/pre-commit` hook on every commit. |
| `make remove-ci` | Delete the CI / pre-commit / linting scaffolding for a clean slate. See [Removing the CI](#removing-the-ci). |

## Local pre-commit flow

`make init` sets `core.hooksPath` to [.githooks/](.githooks/). On every commit, git
runs [.githooks/pre-commit](.githooks/pre-commit) — a thin shim that execs
`make precommit`. The full hook definition lives in the `Makefile`, not the shim, so
linter invocations are changed in one place.

`make precommit` operates only on **staged Python files**:

1. **Auto-fix** — `ruff format` then `ruff check --fix`, re-staging the results.
2. **Verify** — `ruff format --check`, `ruff check`, `pydoclint` (Google style),
   and `ty` over the source tree.

Heavier global gates are intentionally left out of the hook (to keep commits fast)
and run only in CI: the version-bump guard, vendored-file enforcement, `vulture`,
and the repo-wide `hadolint` / `yamllint` sweep.

## GitHub Actions CI

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on pull requests to `main`
and pushes to `main`. Every job runs in Docker. Jobs (besides `version-check`) run in
parallel after the guards pass.

| Job | What it does |
|---|---|
| **version-check** (Repo guards) | Enforces version bumps vs `origin/main` ([.githooks/check_version_bumps.sh](.githooks/check_version_bumps.sh)), and locks vendored drivers — a vendored file may only change if the package's `VENDOR.md` changes in the same diff. All other jobs depend on this. |
| **lint** | Runs the comprehensive linter sweep via [.githooks/run-linters.sh](.githooks/run-linters.sh) over all `*.py`, `*.yml`/`*.yaml`, and Dockerfiles: `ruff` (format + check), `vulture`, `pydoclint`, `ty`, `hadolint`, `yamllint`. Shares the same linter images as the local hook. |
| **test** | `docker compose up matter-native-test` — the host C++ unit test for the coalesced Matter state snapshot policy — then `docker compose up pytest` — full suite with a 90% coverage gate (`fail_under = 90` in [pyproject.toml](pyproject.toml)). |
| **compile-firmware** | Matrix over each project × target (RP2040+RP2350 via `pi-compile`, ESP32-S3 via `esp32-compile`); verifies each firmware artifact is non-empty and within its [size budget](#firmware-size-budgets). Includes `matter` and `matter-radar-sensor`, which are ESP32-S3-only (excluded from the `rp` target — no `pi-compile` service) and mint fresh Matter commissioning credentials on every build. |
| **vuln-check** | `uv-secure` scans [uv.lock](uv.lock) (image built via `docker buildx bake scan-uv-secure`); fails only when a vulnerable dependency has a fixed release available. |
| **cve-scan** | Trivy image scan (HIGH/CRITICAL) of the `scan-viz`, `scan-pytest`, and `scan-uv-secure` bake images (`docker buildx bake`). Report-only — does not fail the build. |
| **all-checks-pass** | Aggregates the results of the above into a single required status. |

### Firmware size budgets

The `compile-firmware` job is the only place firmware size is enforced — it's a
cloud-only gate (no local equivalent), because the artifacts are build outputs
that aren't checked in. After each compile it globs the produced artifacts and
fails if any single file is empty or over budget:

| Artifact | Glob | Budget |
|---|---|---|
| RP2040 + RP2350 UF2 | `outputs/*.uf2` | 3 MiB (3,145,728 B) per file |
| ESP32-S3 image | `outputs/*.bin` | 2 MiB (2,097,152 B) per file |
| ESP32-S3 image (Matter projects) | `outputs/*.bin` | 4 MiB (4,194,304 B) |

The budgets live in the `compile-firmware` matrix `include` (`max_bytes`) in
[.github/workflows/ci.yml](.github/workflows/ci.yml). The first two sit ~10–15%
above the current largest artifact, so they catch a few-hundred-KB regression
while leaving real headroom under the chips' flash (RP2040 2 MB, RP2350/ESP32-S3
4 MB).

The UF2 check is per-file by design: a project emits one universal
`app.rp2040.rp2350.uf2` today, but may later split into separate per-chip UF2s if
one grows too large — each is then checked against the same budget independently.
Bump `max_bytes` deliberately when a size increase is justified.

A Matter image is deterministically padded to the whole flash on every build
regardless of application code size — `build.py`'s own `_validate_merged_image`
already requires exactly that size. This CI check exists for parity.

### Renovate

Dependency updates are handled by self-hosted Renovate:
[.github/workflows/renovate.yml](.github/workflows/renovate.yml) runs Mondays at
06:00 UTC (and on demand via `workflow_dispatch`); behavior is configured in
[.github/renovate.json](.github/renovate.json). It bumps Docker base-image digests,
GitHub Action SHAs, and uv/PEP 621 deps + `uv.lock`. Each update opens a PR that
re-runs `ci.yml`, so new pins are build-verified before merge.

## Linter infrastructure

[Dockerfile.linters](Dockerfile.linters) defines one image per tool — `ruff-lint`,
`hadolint-lint`, `yamllint-lint`, `vulture-lint`, `pydoclint-lint`, and `uv-secure`.
Tool versions are pinned in [pyproject.toml](pyproject.toml)'s `lint` dependency-group
and resolved through [uv.lock](uv.lock), so local and CI runs use identical versions.
Both [.githooks/run-linters.sh](.githooks/run-linters.sh) (CI) and the `precommit`
target build these images with `docker buildx bake` ([docker-bake.hcl](docker-bake.hcl));
buildkit caches across runs, so a clean checkout pays the build once.

### Builds: bake vs compose

Two build front-ends, split by purpose:

- **[docker-bake.hcl](docker-bake.hcl)** builds the *build-only* images — the
  linters, the `typecheck` image, and the CVE-scan images. The `typecheck` and
  `scan-pytest` targets need the internal-package wheels, so bake wires them in as
  a build context (`contexts = { wheels = "target:wheels" }`), building the wheels
  stage from [Dockerfile.host](Dockerfile.host) once per invocation.
- **[docker-compose.yaml](docker-compose.yaml)** builds *and runs* the services
  that need a runtime — `pytest` (volume mounts), firmware compiles, `viz` (port),
  and `uv` (bind-mount). It supplies the same wheels context its own way, via
  `additional_contexts: wheels: service:wheels`.

The payoff: the wheels build logic lives only in `Dockerfile.host` —
`Dockerfile.tests` just does `COPY --from=wheels`, and both front-ends provide
that context. No stage is mirrored across Dockerfiles.

Standalone linter configs live at the repo root:

| File | Tool |
|---|---|
| [.hadolint.yaml](.hadolint.yaml) | hadolint (Dockerfile lint) — error-level rules block CI |
| [.yamllint.yaml](.yamllint.yaml) | yamllint (YAML style) |
| [.vulture_allowlist.py](.vulture_allowlist.py) | vulture — names that look unused but are load-bearing |
| `[tool.ruff]` / `[tool.ty.*]` / `[tool.pydoclint]` / `[tool.vulture]` in [pyproject.toml](pyproject.toml) | ruff, ty, pydoclint, vulture config |

## Removing the CI

`make remove-ci` strips the CI / pre-commit / linting scaffolding so you can fork the
project and wire up your own. It deletes from the working tree only (not `git rm`), so
you review and stage the deletions yourself.

**Deleted:**

- [.github/](.github/) — the entire directory: `ci.yml`, `renovate.yml`,
  `renovate.json`, `CODEOWNERS`, and the pull-request template.
- `.githooks/pre-commit`, `.githooks/.initialized`
- `.githooks/run-linters.sh`, `.githooks/check_version_bumps.sh`
- [Dockerfile.linters](Dockerfile.linters), [docker-bake.hcl](docker-bake.hcl)
- [.hadolint.yaml](.hadolint.yaml), [.yamllint.yaml](.yamllint.yaml),
  [.vulture_allowlist.py](.vulture_allowlist.py)

It also runs `git config --local --unset core.hooksPath` so git stops looking for the
deleted hook, and overwrites the `Makefile` with a minimal stub (dropping the now-dead
`init` / `precommit` / `remove-ci` targets).

**Kept on purpose:**

- **Lint config in [pyproject.toml](pyproject.toml)** — the `[tool.ruff]`, `[tool.ty]`,
  `[tool.pydoclint]`, `[tool.vulture]` tables and the `lint` / `typecheck`
  dependency-groups are left untouched (the `typecheck` group is shared with the `test`
  group). They sit inert without the tools; remove them by hand if you want a full purge.
