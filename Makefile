SHELL := /bin/bash

LINT_IMAGES := local/ruff:latest local/pydoclint:latest local/typecheck:latest

.PHONY: init build-linters precommit remove-ci

build-linters:
	@docker buildx bake -f docker-bake.hcl ruff pydoclint typecheck

init: build-linters
	@set -euo pipefail; \
	repo_root="$$(git rev-parse --show-toplevel 2>/dev/null || true)"; \
	if [[ -z "$$repo_root" ]]; then \
		echo "error: must run from inside the repository."; \
		exit 1; \
	fi; \
	hooks_dir="$$repo_root/.githooks"; \
	initialized_marker="$$hooks_dir/.initialized"; \
	if [[ ! -d "$$hooks_dir" ]]; then \
		echo "error: expected hooks directory at $$hooks_dir."; \
		exit 1; \
	fi; \
	echo "Setting core.hooksPath to $$hooks_dir..."; \
	git config --local core.hooksPath "$$hooks_dir"; \
	chmod +x "$$hooks_dir/pre-commit"; \
	touch "$$initialized_marker"; \
	echo "pre-commit hook ready (core.hooksPath=$$hooks_dir)."

# Self-contained pre-commit: depends only on docker and git. Two phases:
# (1) auto-fix staged Python in place (ruff format, ruff check --fix) and
# re-stage; (2) verify ruff + pydoclint + ty on staged Python. Heavier global
# gates (the version-bump guard, vendored-file enforcement, vulture, and the
# repo-wide hadolint / yamllint sweep) stay in CI.
#
# Images must already exist (built by `make init` or `make build-linters`).
# No builds happen in this path — it is pure docker-run.
precommit:
	@set -uo pipefail; \
	repo_root="$$(git rev-parse --show-toplevel)"; \
	cd "$$repo_root"; \
	image_ruff="local/ruff:latest"; \
	image_pydoclint="local/pydoclint:latest"; \
	image_typecheck="local/typecheck:latest"; \
	missing=0; \
	for img in $$image_ruff $$image_pydoclint $$image_typecheck; do \
		if ! docker image inspect "$$img" >/dev/null 2>&1; then \
			echo "error: image $$img not found. Run 'make init' first." >&2; \
			missing=1; \
		fi; \
	done; \
	if (( missing )); then exit 1; fi; \
	mapfile -d '' -t py_files < <(git diff --cached --name-only --diff-filter=ACMR -z | grep -zE '[.]py$$' || true); \
	if (( $${#py_files[@]} > 0 )); then \
		echo "[pre-commit] ruff format (auto-fix) on staged files"; \
		docker run --rm -v "$$repo_root":/work -w /work "$$image_ruff" format -- "$${py_files[@]}" || exit 1; \
		git add -- "$${py_files[@]}"; \
		echo "[pre-commit] ruff check --fix on staged files"; \
		docker run --rm -v "$$repo_root":/work -w /work "$$image_ruff" check --fix --force-exclude -- "$${py_files[@]}" || exit 1; \
		git add -- "$${py_files[@]}"; \
		fail=0; \
		echo "[lint] ruff format --check"; \
		docker run --rm -v "$$repo_root":/work -w /work "$$image_ruff" format --check || fail=1; \
		echo "[lint] ruff check"; \
		docker run --rm -v "$$repo_root":/work -w /work "$$image_ruff" check --force-exclude || fail=1; \
		echo "[lint] pydoclint"; \
		docker run --rm -v "$$repo_root":/work -w /work "$$image_pydoclint" --style=google --allow-init-docstring=True . || fail=1; \
		echo "[lint] ty check"; \
		docker run --rm -v "$$repo_root/firmware-packages":/work/firmware-packages:ro -v "$$repo_root/cpython-packages":/work/cpython-packages:ro -v "$$repo_root/projects":/work/projects:ro "$$image_typecheck" || fail=1; \
		exit "$$fail"; \
	fi

# Strip the CI / pre-commit / linting scaffolding so a fork can wire up its own.
# Deletes the GitHub Actions config, the pre-commit hook, the CI-only guard and
# linter scripts, the linter Dockerfile, the bake file, and the standalone lint
# configs.
# pyproject.toml lint tables are left in place (inert without the tools; remove
# by hand if wanted).
# Deletions hit the working tree only (not `git rm`) so you review and stage them.
# Finally self-cleans: drops the now-dead init/precommit/remove-ci targets by
# overwriting this Makefile with a stub (safe — make already parsed the recipe).
remove-ci:
	@set -uo pipefail; \
	repo_root="$$(git rev-parse --show-toplevel)"; \
	cd "$$repo_root"; \
	echo "Removing CI / pre-commit / linting files..."; \
	rm -rf .github; \
	rm -f .githooks/pre-commit .githooks/.initialized \
	      .githooks/run-linters.sh .githooks/check_version_bumps.sh; \
	rm -f Dockerfile.linters docker-bake.hcl .hadolint.yaml .yamllint.yaml .vulture_allowlist.py; \
	git config --local --unset core.hooksPath 2>/dev/null || true; \
	printf '%s\n%s\n' 'SHELL := /bin/bash' '# CI tooling removed via `make remove-ci`.' > Makefile; \
	echo "Done. Removed CI / pre-commit / linting scaffolding."; \
	echo "Review with 'git status' and commit when ready."
