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
| **test** | `docker compose up pytest` — full suite with a 90% coverage gate (`fail_under = 90` in [pyproject.toml](pyproject.toml)). |
| **compile-firmware** | Matrix over each project × target (RP2040+RP2350 via `pi-compile`, ESP32-S3 via `esp32-compile`); verifies the firmware artifact was produced. |
| **vuln-check** | `uv-secure` scans [uv.lock](uv.lock); fails only when a vulnerable dependency has a fixed release available. |
| **cve-scan** | Trivy image scan (HIGH/CRITICAL) of the `viz`, `pytest`, and `uv-secure` images. Report-only — does not fail the build. |
| **all-checks-pass** | Aggregates the results of the above into a single required status. |

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
target build/reuse these images by tag, so a clean checkout pays the build once.

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
- [Dockerfile.linters](Dockerfile.linters)
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
