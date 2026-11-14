<p align="center">
  <img src="https://query.farm/media-kit/products/vgi/vgi-logo.png" alt="Vector Gateway Interface (VGI)" width="320">
</p>

<p align="center"><em>A <a href="https://query.farm">Query.Farm</a> VGI worker for DuckDB.</em></p>

# Parse & Normalize International Addresses in DuckDB

> **vgi-libpostal** · a [Query.Farm](https://query.farm) VGI worker · powered by libpostal

International **address parsing + normalization** in DuckDB SQL, powered by
[libpostal](https://github.com/openvenues/libpostal) — the statistical
international street-address parser/normalizer trained on
[OpenStreetMap](https://www.openstreetmap.org/) — exposed through the
[`postal`](https://github.com/openvenues/pypostal) (pypostal) Python binding and
[VGI](https://query.farm) (Vector Gateway Interface).

```sql
INSTALL vgi FROM community; LOAD vgi;
ATTACH 'postal' (TYPE vgi, LOCATION 'docker://ghcr.io/query-farm/vgi-libpostal:0.4.0');

-- Parse an address into a MAP of components (values are lower-cased)
SELECT postal.parse_address('1600 Pennsylvania Ave NW, Washington, DC 20500');
-- {road=pennsylvania ave nw, city=washington, state=dc, postcode=20500, house_number=1600}

SELECT postal.parse_address('10 Downing St, London SW1A 2AA, UK')['postcode'];  -- 'sw1a 2aa'
SELECT postal.address_city('1600 Pennsylvania Ave NW, Washington, DC 20500');   -- 'washington'

-- Normalize / expand abbreviations
SELECT UNNEST(postal.expand_address('120 E 96th St'));  -- '120 east 96th street', ...

-- Long-format parse: one (label, value) row per component
SELECT * FROM postal.parse_address_components('781 Franklin Ave, Brooklyn, NY 11216');

-- Discover the component labels libpostal can emit
SELECT label FROM postal.address_labels() ORDER BY label;

-- Compose them: find duplicate addresses -- same postcode AND overlapping
-- normalized expansions ('St' = 'Street', 'E' = 'East')
WITH customers(id, addr) AS (VALUES
    (1, '120 E 96th St, New York, NY 10128'),
    (2, '120 East 96th Street, New York NY 10128'),
    (3, '130 E 96th St, New York, NY 10128')),
keyed AS (SELECT id, postal.address_postcode(addr) AS postcode,
                 postal.expand_address(addr) AS forms FROM customers)
SELECT a.id AS id_a, b.id AS id_b
FROM keyed AS a JOIN keyed AS b
  ON a.postcode = b.postcode AND a.id < b.id AND list_has_any(a.forms, b.forms)
ORDER BY id_a, id_b;
-- (1, 2): 130 E 96th St shares the postcode but is a different building
```

---

## Quick start

**Run it from the published Docker image — this is the supported way.** The
worker needs the **libpostal C library and its ~2 GB of trained data models**,
which are **not pip-installable**, so `uv`/`uvx` alone cannot install it. The
image at `ghcr.io/query-farm/vgi-libpostal` (linux/amd64 + linux/arm64, cosign
signed) bakes in libpostal, its data, and the worker, so the only host
requirement is Docker (or Podman / nerdctl):

```sql
INSTALL vgi FROM community;
LOAD vgi;

ATTACH 'postal' AS postal (TYPE vgi, LOCATION 'docker://ghcr.io/query-farm/vgi-libpostal:0.4.0');

SELECT postal.parse_address('10 Downing St, London SW1A 2AA, UK');
```

Change `:0.4.0` to move to a newer release.

The `vgi` extension turns a `docker://` (or `oci://`) LOCATION into
`docker run -i --rm <image> stdio`, pulls the image on first use, and keeps the
container warm in its worker pool across queries. Pin a release tag (`:0.4.0`)
for reproducibility; `:latest` tracks the newest release and `:edge` tracks
`main`. The image is large (~2.8 GB uncompressed), so pull it ahead of time if
you like: `docker pull ghcr.io/query-farm/vgi-libpostal:0.4.0`. libpostal loads
its models on the first parse/expand query (a few seconds), not at ATTACH.

### Other ways to run it

- **Over HTTP**: the same image also serves HTTP (`docker run -p 8000:8000
  ghcr.io/query-farm/vgi-libpostal:0.4.0`, then `ATTACH ... LOCATION
  'http://localhost:8000'`).

- **With `uvx`** (needs libpostal and its data installed on the host). The
  `postal` Python binding compiles against libpostal, so point the compiler at
  it for the first install:

  ```sh
  # macOS: brew install libpostal   (library + ~1.9 GB data)
  # Linux: build from source -- https://github.com/openvenues/libpostal#installation
  export CFLAGS="-I$(brew --prefix libpostal)/include" LDFLAGS="-L$(brew --prefix libpostal)/lib"
  uvx --from git+https://github.com/Query-farm/vgi-libpostal@v0.4.0 vgi-libpostal-worker --help
  ```

  uv caches the built environment, so afterwards the same command works as a
  LOCATION without the flags:

  ```sql
  ATTACH 'postal' AS postal (TYPE vgi, LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-libpostal@v0.4.0 vgi-libpostal-worker');
  ```

  (On Linux, also make sure the libpostal shared library is on the loader path,
  e.g. `sudo ldconfig` or `LD_LIBRARY_PATH`.)

- **From a local checkout** (`git clone https://github.com/Query-farm/vgi-libpostal`),
  export the same `CFLAGS`/`LDFLAGS`, run `uv sync --extra dev` once, and point
  `LOCATION` at `uv run --project /path/to/vgi-libpostal --no-sync vgi-libpostal-worker` —
  `--no-sync` reuses the prebuilt `.venv` instead of recompiling `postal` on
  every launch.

### Build from source

To build and test the worker yourself, see
[Development & testing](#development--testing).

---

## Functions

### Scalar functions

| Function | Returns | Description |
|---|---|---|
| `parse_address(text)` | `MAP(VARCHAR, VARCHAR)` | libpostal components keyed by label (`road`, `city`, `state`, `postcode`, `country`, `house_number`, `unit`, …). |
| `expand_address(text)` | `VARCHAR[]` | Normalized expansions (`St` → `street`, `E` → `east`, …). |
| `address_house_number(text)` | `VARCHAR` | The `house_number` component, or NULL. |
| `address_road(text)` | `VARCHAR` | The `road` (street) component, or NULL. |
| `address_unit(text)` | `VARCHAR` | The `unit` (apartment/suite) component, or NULL. |
| `address_city(text)` | `VARCHAR` | The `city` component, or NULL. |
| `address_state(text)` | `VARCHAR` | The `state` (province/region) component, or NULL. |
| `address_postcode(text)` | `VARCHAR` | The `postcode` (ZIP) component, or NULL. |
| `address_country(text)` | `VARCHAR` | The `country` component, or NULL. |

### Table functions

| Function | Yields | Description |
|---|---|---|
| `parse_address_components(text)` | `(label VARCHAR, value VARCHAR)` | One row per parsed component (long format). |
| `address_labels()` | `(label VARCHAR)` | Every component label libpostal can emit (discovery). |

### Semantics

- **libpostal lower-cases its output.** `address_state('… NY …')` returns
  `'ny'`, not `'NY'`. Filter and compare against lower case.
- **NULL input → NULL output** (NULL map / NULL list / NULL string / no rows).
- **Empty string → empty map / empty list / no rows** — never an error.
- A missing component (e.g. no country in a bare US address) → **NULL** from the
  extractor, or simply absent from the map / long-format rows.
- libpostal labels can be subtle: a New York City **borough** like *Brooklyn*
  comes back as `city_district` (with `city` = the larger municipality), and a
  neighbourhood as `suburb`. Use `address_labels()` to see the full label set.

---

## Development & testing

```sh
export CFLAGS="-I$(brew --prefix libpostal)/include" LDFLAGS="-L$(brew --prefix libpostal)/lib"
uv sync --extra dev

uv run --no-sync pytest -q          # unit (pure logic) + integration (Client RPC)
make test-sql                       # end-to-end SQL via haybarn-unittest (authoritative)
make test                           # both
uv run --no-sync ruff check . && uv run --no-sync mypy vgi_libpostal/
```

`make test-sql` sets `VGI_LIBPOSTAL_WORKER=".venv/bin/python
libpostal_worker.py"` (the prebuilt venv, like `uv run --no-sync`), puts `~/.local/bin` on `PATH`, and runs
`haybarn-unittest` over `test/sql/*`. Install the runner once with
`uv tool install --prerelease allow 'haybarn-unittest>=2.0.0rc11,<2.1'`.

The SQL suite is the authoritative behaviour gate — the in-process pytest path
can pass while the real ATTACH+SELECT wire path is broken. Run both.

---

## Layout

```
libpostal_worker.py    repo-root stdio entry point; PEP 723 header; main()
vgi_libpostal/
  addresses.py         pure parse/expand logic over the `postal` binding (no Arrow/VGI)
  scalars.py           per-row scalars: parse_address (MAP), expand_address (LIST), extractors
  tables.py            parse_address_components (long) + address_labels (discovery)
  schema_utils.py      pa.Field comment / column-doc helper
tests/                 pytest: test_addresses (pure) + test_scalars (Client RPC) + test_tables
test/sql/*.test        haybarn-unittest sqllogictest — authoritative E2E
Makefile               test / test-unit / test-sql / lint
```

---

## Licensing

Permissive throughout:

- **This worker** — MIT (see [LICENSE](LICENSE)).
- **pypostal** (`postal`) — MIT.
- **libpostal** (C library + data models) — MIT.

`vgi-python` itself is under the Query Farm Source-Available License; see that
project for its terms.

---

Created by [Query.Farm](https://query.farm).

---

## Authorship & License

Written by [Query.Farm](https://query.farm).

Copyright 2026 Query Farm LLC - https://query.farm

## Notebooks

[Executed address-candidate review walkthrough](notebooks/README.md).
