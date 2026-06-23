<p align="center">
  <img src="https://raw.githubusercontent.com/Query-farm/vgi/main/docs/vgi-logo.png" alt="Vector Gateway Interface (VGI)" width="320">
</p>

<p align="center"><em>A <a href="https://query.farm">Query.Farm</a> VGI worker for DuckDB.</em></p>

# vgi-libpostal

International **address parsing + normalization** in DuckDB SQL, powered by
[libpostal](https://github.com/openvenues/libpostal) — the statistical
international street-address parser/normalizer trained on
[OpenStreetMap](https://www.openstreetmap.org/) — exposed through the
[`postal`](https://github.com/openvenues/pypostal) (pypostal) Python binding and
[VGI](https://query.farm) (Vector Gateway Interface).

```sql
INSTALL vgi FROM community; LOAD vgi;
ATTACH 'postal' (TYPE vgi, LOCATION 'uv run --no-sync libpostal_worker.py');

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
```

---

## ⚠️ Heavyweight native dependency — read this first

**This worker does NOT work out of the box from `pip`/`uv` alone.** It depends
on the **libpostal C library and its ~2 GB of machine-learning data models**,
which must be installed **separately** and are **NOT bundled** with this package
and **NOT pip-installable**. The `postal` Python package is only a thin C binding
that *compiles against* libpostal — without the C library present, it will not
even build.

Think of this like [vgi-tika](https://github.com/Query-farm)'s Tesseract OCR
dependency, but **much heavier**: libpostal ships ~2 GB of trained data
(address-parser CRF model, transliteration tables, numeric-expression and
language-classification data).

### Install libpostal

**macOS (Homebrew)** — the easy path; pulls the prebuilt library + data:

```sh
brew install libpostal
# library at  $(brew --prefix libpostal)
# data at     $(brew --prefix libpostal)/share/libpostal   (~1.9 GB)
```

**Linux / from source** — build the C library, then download the ~2 GB data
(takes several minutes and ~2 GB of disk):

```sh
sudo apt-get install -y curl autoconf automake libtool pkg-config
git clone https://github.com/openvenues/libpostal && cd libpostal
./bootstrap.sh
./configure --datadir=/path/to/libpostal-data   # this is where the ~2 GB lands
make -j"$(nproc)" && sudo make install && sudo ldconfig
```

See the [libpostal install guide](https://github.com/openvenues/libpostal#installation)
for Windows and other platforms.

### Build the `postal` binding against it

The `postal` C extension needs to find libpostal's headers and library at build
time. Export the include/lib paths, then sync:

```sh
export CFLAGS="-I$(brew --prefix libpostal)/include"
export LDFLAGS="-L$(brew --prefix libpostal)/lib"
uv sync --extra dev      # compiles `postal` against libpostal
```

(On Linux, point `CFLAGS`/`LDFLAGS` at your `--prefix` and set
`LD_LIBRARY_PATH` to its `lib/` directory.)

---

## Install & attach

```sh
git clone <this repo> && cd vgi-libpostal
export CFLAGS="-I$(brew --prefix libpostal)/include" LDFLAGS="-L$(brew --prefix libpostal)/lib"
uv sync --extra dev
```

Attach the worker from any DuckDB-compatible engine. **Use `uv run --no-sync`**
as the launch command:

```sql
ATTACH 'postal' (TYPE vgi, LOCATION 'uv run --no-sync libpostal_worker.py');
```

### Why `--no-sync`?

`postal` is a C extension compiled against libpostal. A bare
`uv run libpostal_worker.py` (using the PEP 723 inline dependencies) would
**rebuild pypostal in a fresh ephemeral environment on every single launch** —
slow, and it would need `CFLAGS`/`LDFLAGS` re-exported each time. `uv run
--no-sync` reuses the project's already-built `.venv` (where `postal` is already
compiled), so the worker starts fast. Build the venv once with `uv sync`; launch
with `--no-sync`.

The PEP 723 header in `libpostal_worker.py` still lists `postal` for
documentation/portability, but the prebuilt-venv path is the supported one.

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

`make test-sql` sets `VGI_LIBPOSTAL_WORKER="uv run --no-sync
libpostal_worker.py"`, puts `~/.local/bin` on `PATH`, and runs
`haybarn-unittest` over `test/sql/*`. Install the runner once with
`uv tool install haybarn-unittest`.

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

Written by [Query.Farm](https://query.farm) — every VGI worker is designed and built by Query.Farm.

Copyright 2026 Query Farm LLC - https://query.farm

