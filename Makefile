# vgi-libpostal — dev and test targets.
#
# Usage:
#   make test       # unit/integration (pytest) + end-to-end SQL (haybarn-unittest)
#   make test-unit  # pytest only
#   make test-sql   # DuckDB sqllogictest .test files via haybarn-unittest
#   make lint       # ruff format check + ruff check + mypy
#
# NATIVE DEPENDENCY: this worker needs the libpostal C library + ~2 GB data
# models (NOT pip-installable, NOT bundled). On macOS: `brew install libpostal`.
# The `postal` (pypostal) binding is a C extension compiled against it, so
# `uv sync` must run with the include/lib paths exported:
#
#   export CFLAGS="-I$(shell brew --prefix libpostal)/include"
#   export LDFLAGS="-L$(shell brew --prefix libpostal)/lib"
#   uv sync --extra dev
#
# WORKER LAUNCH: a bare `uv run libpostal_worker.py` would rebuild pypostal in a
# fresh ephemeral env on every ATTACH (slow, needs CFLAGS/LDFLAGS each time).
# `uv run --no-sync` reuses the project `.venv` where pypostal is already built,
# so that is the worker command DuckDB uses for ATTACH.

# Worker command DuckDB uses for ATTACH (overridable). Launch straight from the
# already-built project .venv (where pypostal is compiled) — same as CI's
# WORKER_CMD — so ATTACH never re-resolves deps / rebuilds pypostal and always
# runs against the pinned SDK in .venv (not a stale PEP-723 ephemeral env).
WORKER_STDIO    ?= .venv/bin/python libpostal_worker.py

# haybarn-unittest lives in the uv tools bin; keep it on PATH.
HAYBARN_BIN     ?= $(HOME)/.local/bin
TEST_DIR         = .
TEST_PATTERN     = test/sql/*

.PHONY: test test-unit test-sql lint

test: test-unit test-sql

test-unit:
	uv run --no-sync pytest -q

test-sql:
	PATH="$(HAYBARN_BIN):$$PATH" \
		VGI_LIBPOSTAL_WORKER="$(WORKER_STDIO)" \
		haybarn-unittest --test-dir "$(TEST_DIR)" "$(TEST_PATTERN)"

lint:
	uv run --no-sync ruff format --check .
	uv run --no-sync ruff check .
	uv run --no-sync mypy vgi_libpostal/
