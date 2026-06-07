SHELL := /bin/bash

.PHONY: init precommit remove-ci
init:
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

# Self-contained pre-commit: the full local check, depending only on docker and
# git. It does not source any project script. Two phases, mirroring the old
# hook: (1) auto-fix staged Python in place (ruff format, ruff check --fix) and
# re-stage; (2) verify ruff + pydoclint + ty on staged Python. Heavier global
# gates (the version-bump guard, vendored-file enforcement, vulture, and the
# repo-wide hadolint / yamllint sweep) stay in CI. Linter images
# reuse the same tags CI builds, so a clean checkout pays the build once.
precommit:
	@set -uo pipefail; \
	repo_root="$$(git rev-parse --show-toplevel)"; \
	cd "$$repo_root"; \
	bake_file="docker-bake.hcl"; \
	image_ruff="local/ruff:latest"; \
	image_pydoclint="local/pydoclint:latest"; \
	image_typecheck="local/typecheck:latest"; \
	mapfile -d '' -t py_files < <(git diff --cached --name-only --diff-filter=ACMR -z | grep -zE '[.]py$$' || true); \
	if (( $${#py_files[@]} > 0 )); then \
		docker buildx bake -f "$$bake_file" ruff; \
		echo "[pre-commit] ruff format (auto-fix) on staged files"; \
		docker run --rm -v "$$repo_root":/work -w /work -e RUFF_CACHE_DIR=/tmp/ruff "$$image_ruff" format -- "$${py_files[@]}" || exit 1; \
		git add -- "$${py_files[@]}"; \
		echo "[pre-commit] ruff check --fix on staged files"; \
		docker run --rm -v "$$repo_root":/work -w /work -e RUFF_CACHE_DIR=/tmp/ruff "$$image_ruff" check --fix --force-exclude -- "$${py_files[@]}" || exit 1; \
		git add -- "$${py_files[@]}"; \
	fi; \
	fail=0; \
	if (( $${#py_files[@]} > 0 )); then \
		docker buildx bake -f "$$bake_file" pydoclint typecheck; \
		echo "[lint] ruff format --check ($${#py_files[@]} file(s))"; \
		docker run --rm -v "$$repo_root":/work -w /work -e RUFF_CACHE_DIR=/tmp/ruff "$$image_ruff" format --check -- "$${py_files[@]}" || fail=1; \
		echo "[lint] ruff check ($${#py_files[@]} file(s))"; \
		docker run --rm -v "$$repo_root":/work -w /work -e RUFF_CACHE_DIR=/tmp/ruff "$$image_ruff" check --force-exclude -- "$${py_files[@]}" || fail=1; \
		echo "[lint] pydoclint ($${#py_files[@]} file(s))"; \
		docker run --rm -v "$$repo_root":/work -w /work "$$image_pydoclint" --style=google --allow-init-docstring=True -- "$${py_files[@]}" || fail=1; \
		echo "[lint] ty check"; \
		docker run --rm -v "$$repo_root/firmware-packages":/work/firmware-packages:ro -v "$$repo_root/cpython-packages":/work/cpython-packages:ro -v "$$repo_root/projects":/work/projects:ro "$$image_typecheck" || fail=1; \
	fi; \
	exit "$$fail"

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
