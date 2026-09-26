# tools

Each directory under `tools/` is one host tool. Its own `.md` file, or the module docstrings of its scripts, describe what it does.

Tools run from the checkout and are never installed. Python tools are bind-mounted into the Docker stage that runs them, and `tools/` is mounted at `/tools` for pytest.
