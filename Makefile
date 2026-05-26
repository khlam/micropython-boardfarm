SHELL := /bin/bash

.PHONY: init
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
