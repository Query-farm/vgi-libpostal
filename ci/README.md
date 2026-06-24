# CI: the vgi-libpostal worker integration suite

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs a pure-Python
`lint` job on every push / PR, and a heavy, **gated** `integration` job (builds
libpostal + downloads ~2 GB of data) that runs this repo's sqllogictest suite
(`test/sql/*.test`) against the vgi-libpostal worker through the **real DuckDB
`vgi` extension**.

## Two tiers, honestly gated

- **`lint`** — pure-Python, needs NO libpostal. Always runs, always meaningful.
- **`integration`** — builds the libpostal C library from source (+ ~2 GB data
  download, several minutes), compiles pypostal against it, then runs pytest +
  the SQL E2E. **Gated behind `if: vars.RUN_LIBPOSTAL == 'true'`** (default OFF
  to keep PRs fast) — so on a normal PR this job is **SKIPPED**. Flip the
  `RUN_LIBPOSTAL` repo variable to `true` on a runner that can afford the build.

## How the E2E works (no extension C++ build)

Rather than building the vgi DuckDB extension from source, CI drives a
**prebuilt** standalone `haybarn-unittest` and installs the **signed** `vgi`
extension from the Haybarn community channel:

1. **Install the worker** — `uv sync --frozen --extra dev --extra http` (with
   `CFLAGS`/`LDFLAGS`/`LD_LIBRARY_PATH` pointed at the just-built libpostal, so
   pypostal's C extension compiles). The `http` extra adds waitress for the http
   leg.
2. **Download the runner** — the `haybarn_unittest-linux-amd64` asset.
3. **Preprocess** — [`preprocess-require.awk`](preprocess-require.awk) rewrites
   each `require <ext>` into an explicit signed `INSTALL/LOAD`, and injects
   `INSTALL vgi FROM community;` before each bare `LOAD vgi;`.
4. **Run** — [`run-integration.sh`](run-integration.sh) stages the preprocessed
   tree, resolves `VGI_LIBPOSTAL_WORKER` (the ATTACH `LOCATION`) per `$TRANSPORT`,
   warms the extension cache once, then runs the suite in a single
   `haybarn-unittest` invocation. Any failed assertion fails the job.

The worker runs from the compiled `.venv` via plain `.venv/bin/python` (the
`--no-sync` discipline — see CLAUDE.md), so no pypostal rebuild happens per
ATTACH / per worker boot.

## Transport matrix (subprocess | http | unix)

When the gate is on, the same `test/sql/*.test` suite runs over all three VGI
transports — the extension picks the transport from the `LOCATION` string the
`.test` files `ATTACH`, and `run-integration.sh` builds that string from
`$TRANSPORT`:

| `TRANSPORT`  | `VGI_LIBPOSTAL_WORKER` (LOCATION)         | How the worker is reached |
|--------------|-------------------------------------------|---------------------------|
| `subprocess` | `.venv/bin/python libpostal_worker.py`    | extension spawns the worker per query; Arrow IPC over stdin/stdout (default) |
| `http`       | `http://127.0.0.1:<port>`                 | harness boots `libpostal_worker.py --http --port 0 --port-file <f>`, waits for the port-file, then ATTACHes that URL |
| `unix`       | `unix:///tmp/libpostal-<pid>.sock`        | harness boots `libpostal_worker.py --unix <sock>`, waits for the socket, then ATTACHes it |

The gated `integration` job is a `transport: [subprocess, http, unix]` matrix
(ubuntu-only — the libpostal native build in this job is Linux-specific); each
leg runs `ci/run-integration.sh` with `TRANSPORT=<t>`.

### Port / readiness discovery

- **http**: the worker writes its auto-selected port to `--port-file`
  atomically, so the harness watches for that file (not stdout). Boot line:
  `libpostal_worker.py --http --port 0 --port-file <f>`.
- **unix**: the worker binds the socket and prints `UNIX:<abs-path>`; the
  harness polls for the socket file (`test -S`). Boot line:
  `libpostal_worker.py --unix <sock>`.

Both out-of-band server processes run with cwd = the repo root and are
trap-killed on exit.

### HTTP transport needs the `httpfs` extension (resolved, not gated)

The vgi extension implements HTTP transport on top of DuckDB's **httpfs**
extension, so an `http://` ATTACH binds with `VGI HTTP transport requires the
httpfs extension` unless httpfs is loaded first. This is a **dependency**, not a
protocol limitation, so we resolve it: the http leg injects a signed `INSTALL
httpfs FROM core; LOAD httpfs;` into each staged `.test` (after the awk-injected
`LOAD vgi;`). The leg also needs the worker's `http` extra (waitress) —
`pyproject.toml` ships an `http` extra (`vgi-python[http]`), the PEP 723 header
lists it, and CI runs `uv sync --frozen --extra dev --extra http`.

> **Sharp edge — the runner silently SKIPs HTTP errors.** The haybarn/DuckDB
> sqllogictest runner's default skip list skips any statement whose error
> contains `"HTTP"` or `"Unable to connect"`, so a broken http setup reports
> "All tests were skipped" — a green-looking **fake pass**.
> `run-integration.sh` fails the leg unless the runner reports `All tests passed
> (N assertions …)` with N > 0 and zero skips.

### Per-transport status (local validation)

Validated locally against a homebrew libpostal install:

- **subprocess**: GREEN — 37 assertions.
- **http**: GREEN — 43 assertions (37 + the injected httpfs INSTALL/LOAD across
  the three `.test` files).
- **unix**: GREEN — 37 assertions.

The suite is per-row scalars (`parse_address`, `expand_address`, `address_*`)
plus two init-drained discovery/parse table functions (`parse_address_components`,
`address_labels`) — no streaming partition-local cursor state, so none of the
inherent HTTP limitations apply and nothing needed gating *within* the suite.
(The whole job remains gated behind `RUN_LIBPOSTAL` for build cost only.)

## Run it locally

```bash
export CFLAGS="-I$(brew --prefix libpostal)/include" LDFLAGS="-L$(brew --prefix libpostal)/lib"
uv sync --python 3.13 --extra dev --extra http
# macOS: export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix libpostal)/lib"
HAYBARN_UNITTEST=/path/to/haybarn-unittest \
WORKER_CMD="$PWD/.venv/bin/python $PWD/libpostal_worker.py" \
  TRANSPORT=subprocess ci/run-integration.sh    # or TRANSPORT=http / TRANSPORT=unix
```

`TRANSPORT` defaults to `subprocess`, and `WORKER_CMD` defaults to
`uv run --no-sync --python 3.13 <repo>/libpostal_worker.py`.
