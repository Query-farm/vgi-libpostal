# CLAUDE.md — vgi-libpostal

Contributor/agent notes. User-facing docs live in `README.md`; this is the
"how it's built and where the sharp edges are" companion.

## What this is

A [VGI](https://query.farm) worker exposing **international address parsing +
normalization** to DuckDB/SQL, backed by
[libpostal](https://github.com/openvenues/libpostal) (the statistical
OSM-trained address parser, MIT) via the
[`postal`](https://github.com/openvenues/pypostal) (pypostal, MIT) binding.
`libpostal_worker.py` assembles every function into one `postal` catalog (single
`main` schema) over stdio. Built from the same template as the sibling
`vgi-conform` / `vgi-calendar` workers.

## Layout

```
libpostal_worker.py    repo-root stdio entry point; PEP 723 header; main()
vgi_libpostal/
  addresses.py         pure parse/expand logic over the `postal` binding; no Arrow/VGI
  scalars.py           per-row scalars: parse_address (MAP), expand_address (LIST), address_* extractors
  tables.py            parse_address_components (long format) + address_labels (discovery)
  schema_utils.py      pa.Field comment / column-doc helper
tests/                 pytest: test_addresses (pure) + test_scalars (Client RPC) + test_tables (harness)
test/sql/*.test        haybarn-unittest sqllogictest — authoritative E2E
Makefile               test / test-unit / test-sql / lint
```

To add a function: implement the logic in `addresses.py` (pure), wrap it as a
scalar or table function in the matching module, register it in
`libpostal_worker.py`'s `_FUNCTIONS`.

## THE native dependency — libpostal C library + ~2 GB data models

This is the whole reason the build is non-trivial. **libpostal is NOT
pip-installable and NOT bundled.** The `postal` Python package is a thin C
extension that **compiles against** the libpostal C library; without it, the
`uv sync` build of `postal` fails outright.

- **Install libpostal first.** macOS: `brew install libpostal` (prefix at
  `$(brew --prefix libpostal)`, ~1.9 GB of data under `share/libpostal`). Linux:
  build from source + download ~2 GB data (`./bootstrap.sh && ./configure
  --datadir=... && make && make install && ldconfig`).
- **Build the binding with the include/lib paths exported:**

  ```sh
  export CFLAGS="-I$(brew --prefix libpostal)/include"
  export LDFLAGS="-L$(brew --prefix libpostal)/lib"
  uv sync --extra dev
  ```

  Without these, `postal`'s C extension can't find `libpostal.h` / `-lpostal`.
  (On Linux also set `LD_LIBRARY_PATH` to the libpostal `lib/` at runtime.)

## Worker-launch decision — `uv run --no-sync` (do NOT drop this)

A bare `uv run libpostal_worker.py` reads the PEP 723 inline deps and provisions
a **fresh ephemeral env on every launch** — which means it would **recompile
pypostal against libpostal on every single ATTACH**. That's slow and needs
`CFLAGS`/`LDFLAGS` re-exported each time.

The fix: launch from the already-built project `.venv` with **`uv run
--no-sync`**, which skips dependency resolution and reuses the compiled `postal`.
So:

- The worker command for `ATTACH` is `uv run --no-sync libpostal_worker.py`.
- `Makefile`'s `test-sql` sets `VGI_LIBPOSTAL_WORKER="uv run --no-sync
  libpostal_worker.py"`.
- The PEP 723 header in `libpostal_worker.py` still lists `postal` for
  documentation/portability, but the tested path is the prebuilt venv.

`make test-unit` / `lint` also use `uv run --no-sync` so they never trigger a
rebuild.

## Sharp edges (learned the hard way)

1. **MAP / LIST scalar returns need an explicit `Returns(arrow_type=...)`.** The
   SDK cannot infer the key/value or element types of a `MAP` / `LIST` from the
   Python annotation, so:
   - `parse_address` → `Returns(arrow_type=pa.map_(pa.string(), pa.string()))`
   - `expand_address` → `Returns(arrow_type=pa.list_(pa.string()))`
   This is the same requirement `vgi-calendar` hit for its TIMESTAMPTZ scalars
   (`Returns(arrow_type=pa.timestamp(...))`). Build the arrays with the matching
   `pa.array(..., type=_MAP_TYPE/_LIST_TYPE)` so the wire type lines up.
2. **`haybarn-unittest` silently SKIPS `require vgi`.** Under haybarn the
   extension isn't autoloaded for `require`, so a `.test` using `require vgi` is
   SKIPPED (looks green, runs nothing). Use an explicit `statement ok` /
   `LOAD vgi;` instead — every `.test` here does.
3. **Scalar calls in `.test` files must be catalog-qualified.** After
   `ATTACH 'postal' AS postal`, unqualified `parse_address(...)` raises
   `Catalog Error: Scalar Function ... does not exist` (the catalog isn't the
   default). Qualify everything: `postal.parse_address(...)`. (Found this in the
   first SQL run.)
4. **`len()` doesn't apply to a MAP.** To assert an empty map, use
   `len(map_keys(parse_address('')))` (or `cardinality`), not `len(map)`.
5. **libpostal LOWER-CASES all output.** `address_state('… NY …')` → `'ny'`.
   Every unit/SQL assertion compares against lower case. Don't "fix" this by
   upper-casing — it's intrinsic to libpostal's normalization.
6. **libpostal labels are statistical and sometimes surprising.** For
   `781 Franklin Ave … Brooklyn NY 11216`, libpostal tags *Brooklyn* as
   `city_district` (a borough) and a neighbourhood as `suburb` — **not** `city`.
   So test vectors that assert `city` use addresses where libpostal actually
   emits `city` (e.g. `1600 Pennsylvania Ave NW, Washington, DC 20500` →
   `city=washington`; `… New York NY …` → `city=new york`). The Franklin Ave
   vector is asserted on `road`/`state`/`postcode`/`house_number`, which are
   stable. `address_labels()` lists the full label set.

## Testing

```sh
export CFLAGS="-I$(brew --prefix libpostal)/include" LDFLAGS="-L$(brew --prefix libpostal)/lib"
uv sync --extra dev

uv run --no-sync pytest -q     # unit: pure logic (test_addresses) + Client RPC (test_scalars) + harness (test_tables)
make test-sql                  # E2E: haybarn-unittest over test/sql/*  (authoritative)
make test                      # both
uv run --no-sync ruff check . && uv run --no-sync mypy vgi_libpostal/
```

Install the runner once with `uv tool install haybarn-unittest`. **The SQL suite
is authoritative** — the in-process pytest path can pass while the real
ATTACH+SELECT wire path is broken (that's how edges #1/#3 surface).

## CI (`.github/workflows/ci.yml`)

Two tiers, honestly gated:

- **`lint`** — pure-Python, needs NO libpostal. Always runs, always green. Uses
  `uvx ruff` / `uvx mypy` (mypy is tolerant of the un-built `postal` import via
  `ignore_missing_imports`).
- **`e2e`** — builds libpostal from source (+ ~2 GB data download, several
  minutes), compiles pypostal against it, then runs pytest + `make test-sql`.
  This is the authoritative behaviour gate but is **heavy/slow**, so it's gated
  behind `if: vars.RUN_LIBPOSTAL == 'true'` — flip that repo variable on a runner
  that can afford the build. The gating reason is documented in the workflow.

## Conventions

- Per-row, single-value functions are **scalars** (`parse_address`,
  `expand_address`, `address_*`) so they work inline in a projection.
- Set-returning functions are **table functions** (`parse_address_components`,
  `address_labels`). `parse_address_components(text)` takes a positional `text`
  arg with `Arg(0, arrow_type=pa.string())`.
- All licensing is permissive: this worker MIT, pypostal MIT, libpostal MIT.
- Nothing is published/deployed yet; the parent repo verifies + publishes.
