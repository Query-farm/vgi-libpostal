# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http]>=0.8.4",
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

_CATALOG_DESCRIPTION_LLM = (
    "Parse and normalize free-form international postal addresses with libpostal "
    "(an OSM-trained statistical address parser). Break an address string into its "
    "components (house_number, road, unit, city, state, postcode, country, ...), "
    "extract a single component (city, state, postcode, country, road, unit, "
    "house_number), or normalize/expand abbreviations ('St' -> 'street', 'E' -> "
    "'east') for matching and deduplication. Use for address parsing, geocoding "
    "pre-processing, address standardization, and record linkage in SQL. Output is "
    "lower-cased; an empty string yields an empty result, NULL yields NULL."
)

_CATALOG_DESCRIPTION_MD = (
    "# postal\n\n"
    "International address parsing and normalization powered by "
    "[libpostal](https://github.com/openvenues/libpostal).\n\n"
    "**Scalars:** `parse_address` (MAP), `expand_address` (LIST), and the "
    "`address_*` component extractors (`address_house_number`, `address_road`, "
    "`address_unit`, `address_city`, `address_state`, `address_postcode`, "
    "`address_country`).\n\n"
    "**Table functions:** `parse_address_components` (long-format parse) and "
    "`address_labels` (discovery).\n\n"
    "Output is lower-cased; empty string -> empty result, NULL -> NULL."
)

_SCHEMA_DESCRIPTION_LLM = (
    "libpostal address parsing and normalization functions: parse an address into "
    "a MAP or long-format rows of components, extract a single component (city, "
    "state, postcode, country, road, unit, house_number), expand abbreviations, "
    "and discover the set of component labels libpostal can emit."
)

_SCHEMA_DESCRIPTION_MD = (
    "Address parsing, component extraction, and normalization functions backed by "
    "libpostal.\n\n"
    "Scalars: `parse_address` (MAP), `expand_address` (LIST), and the `address_*` "
    "component extractors. Table functions: `parse_address_components` (long "
    "format) and `address_labels` (discovery). Output is lower-cased."
)

# VGI506: representative, catalog-qualified example queries for the schema.
_SCHEMA_EXAMPLE_QUERIES = (
    "SELECT postal.main.parse_address('1600 Pennsylvania Ave NW, Washington, DC 20500');\n"
    "SELECT postal.main.parse_address('10 Downing St, London SW1A 2AA, UK')['postcode'];\n"
    "SELECT UNNEST(postal.main.expand_address('120 E 96th St'));\n"
    "SELECT postal.main.address_postcode('781 Franklin Ave, Brooklyn, NY 11216');\n"
    "SELECT * FROM postal.main.parse_address_components('781 Franklin Ave, Brooklyn, NY 11216');\n"
    "SELECT label FROM postal.main.address_labels() ORDER BY label;"
)

_CATALOG_KEYWORDS = (
    "libpostal, address, address parsing, parse address, geocoding, "
    "normalization, standardization, postal, postcode, zip, record linkage, "
    "deduplication, international addresses, openstreetmap"
)

_SCHEMA_KEYWORDS = (
    "libpostal, address, parse, parse_address, expand_address, components, "
    "house_number, road, city, state, postcode, country, unit, labels, "
    "normalization, geocoding"
)

_POSTAL_CATALOG = Catalog(
    name="postal",
    default_schema="main",
    comment="Parse + normalize international postal addresses (libpostal) for SQL",
    source_url="https://github.com/Query-farm/vgi-libpostal",
    tags={
        "vgi.title": "International Address Parsing (libpostal)",
        "vgi.keywords": _CATALOG_KEYWORDS,
        "vgi.doc_llm": _CATALOG_DESCRIPTION_LLM,
        "vgi.doc_md": _CATALOG_DESCRIPTION_MD,
        "vgi.author": "Query.Farm",
        "vgi.copyright": "Copyright 2026 Query Farm LLC - https://query.farm",
        "vgi.license": "MIT",
        "vgi.support_contact": "https://github.com/Query-farm/vgi-libpostal/issues",
        "vgi.support_policy_url": "https://github.com/Query-farm/vgi-libpostal/blob/main/README.md",
    },
    schemas=[
        Schema(
            name="main",
            comment="libpostal address parsing, component extraction, and normalization functions",
            tags={
                "vgi.title": "Address Parsing & Normalization",
                "vgi.keywords": _SCHEMA_KEYWORDS,
                "vgi.source_url": "https://github.com/Query-farm/vgi-libpostal/blob/main/vgi_libpostal",
                "vgi.doc_llm": _SCHEMA_DESCRIPTION_LLM,
                "vgi.doc_md": _SCHEMA_DESCRIPTION_MD,
                # VGI123 classifying tags -- BARE keys (not vgi.-namespaced).
                "domain": "geospatial",
                "category": "parsing",
                "topic": "address-normalization",
                # VGI506: representative example queries for the schema.
                "vgi.example_queries": _SCHEMA_EXAMPLE_QUERIES,
            },
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
