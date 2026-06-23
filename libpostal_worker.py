# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python>=0.8.3",
#     "postal>=1.1",
# ]
# ///
"""VGI worker exposing libpostal address parsing + normalization to SQL.

Assembles the libpostal functions in ``vgi_libpostal`` into a single ``postal``
catalog and runs the worker over stdio (DuckDB subprocess) or HTTP. It parses
and normalizes international postal addresses -- backed by the heavyweight
``libpostal`` C library + ML models -- as DuckDB scalar functions, plus two
discovery / long-format table functions.

IMPORTANT -- launching this worker
----------------------------------
The ``postal`` (pypostal) binding is a C extension that must be **compiled
against libpostal**. A bare ``uv run libpostal_worker.py`` would rebuild it in a
fresh ephemeral environment on every launch (slow, and requires CFLAGS/LDFLAGS
pointing at the brew libpostal install each time). Run it from the already-built
project ``.venv`` instead:

    uv run --no-sync libpostal_worker.py     # reuses .venv where postal is built

(The PEP 723 header above is kept for documentation / portability, but the
tested launch path is the prebuilt venv. See README / CLAUDE.md.)

Usage:
    uv run --no-sync libpostal_worker.py     # serve over stdio (DuckDB subprocess)

    INSTALL vgi FROM community; LOAD vgi;
    ATTACH 'postal' (TYPE vgi, LOCATION 'uv run --no-sync libpostal_worker.py');

    SELECT postal.parse_address('1600 Pennsylvania Ave NW, Washington, DC 20500');
    SELECT postal.parse_address('10 Downing St, London SW1A 2AA, UK')['postcode'];
    SELECT UNNEST(postal.expand_address('120 E 96th St'));
    SELECT postal.address_postcode('781 Franklin Ave, Brooklyn, NY 11216');
    SELECT * FROM postal.parse_address_components('781 Franklin Ave, Brooklyn, NY 11216');
    SELECT * FROM postal.address_labels() ORDER BY label;
"""

from __future__ import annotations

from vgi import Worker
from vgi.catalog import Catalog, Schema

from vgi_libpostal.scalars import SCALAR_FUNCTIONS
from vgi_libpostal.tables import TABLE_FUNCTIONS

_FUNCTIONS: list[type] = [
    *SCALAR_FUNCTIONS,
    *TABLE_FUNCTIONS,
]

_POSTAL_CATALOG = Catalog(
    name="postal",
    default_schema="main",
    schemas=[
        Schema(
            name="main",
            comment="Parse + normalize international postal addresses (libpostal) for SQL",
            functions=list(_FUNCTIONS),
        ),
    ],
)


class LibpostalWorker(Worker):
    """Worker process hosting the ``postal`` catalog."""

    catalog = _POSTAL_CATALOG


def main() -> None:
    """Run the libpostal worker process (stdio or, via flags, HTTP)."""
    LibpostalWorker.main()


if __name__ == "__main__":
    main()
