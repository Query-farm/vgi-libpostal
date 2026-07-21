# Copyright 2026 Query Farm LLC - https://query.farm

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

import json
import threading

from vgi import Worker
from vgi.catalog import Catalog, Schema, Table

from vgi_libpostal import addresses
from vgi_libpostal.scalars import SCALAR_FUNCTIONS
from vgi_libpostal.tables import TABLE_FUNCTIONS, AddressLabelsFunction

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

_CATALOG_DESCRIPTION_MD = """\
# International Address Parsing & Normalization in SQL

**Parse, standardize, and normalize free-form postal addresses from anywhere in the world directly in DuckDB SQL** — turn a messy one-line address string into clean, structured components (house number, road, unit, city, state, postcode, country) without leaving your query.

The `postal` catalog brings [libpostal](https://github.com/openvenues/libpostal) — the open-source statistical address parser trained on OpenStreetMap and open address data — to SQL. It is built for data engineers, analysts, and anyone doing geocoding pre-processing, address standardization, record linkage, entity resolution, or deduplication over customer, shipping, or location data. Because libpostal is trained on real addresses from [OpenStreetMap](https://www.openstreetmap.org) across hundreds of countries and languages, it handles international formats, transliteration, and local abbreviations far better than hand-written regular expressions or fixed format rules.

Under the hood this worker wraps libpostal's C library through its official Python binding, [pypostal](https://github.com/openvenues/pypostal), and exposes it over DuckDB's VGI interface. libpostal does two core things: it *parses* an address — using a sequence model to tag each token with a component label — and it *expands/normalizes* abbreviations into canonical forms (for example `St` → `street`, `E` → `east`, `Rd` → `road`), which is what makes two differently written versions of the same address comparable. All output is lower-cased; an empty string yields an empty result and `NULL` yields `NULL`, so the functions compose cleanly inside larger queries.

## Key concepts

- **Parsing** turns a one-line address into labeled components (house number, road, unit, city, state, postcode, country, and more). Labels are statistical and best-effort — a borough can come back as a city district rather than a city — so treat them as a strong signal, not a strict schema.
- **Normalization / expansion** rewrites abbreviations into canonical, fully-spelled-out forms and can return several valid variants for an ambiguous token; two addresses match when their expansion sets overlap.

## When to reach for it

Use this catalog for geocoding pre-processing, address standardization, record linkage, entity resolution, and deduplication over customer, shipping, or location data — anywhere you need messy free-form addresses made comparable directly in SQL, without shipping data to an external service.

Learn more from the [libpostal source repository](https://github.com/openvenues/libpostal) and its [installation and usage documentation](https://github.com/openvenues/libpostal#installation)."""

_SCHEMA_DESCRIPTION_LLM = (
    "libpostal address parsing and normalization functions: parse an address into "
    "a `MAP` or long-format rows of components, extract a single component (city, "
    "state, postcode, country, road, unit, house_number), expand abbreviations, "
    "and discover the set of component labels libpostal can emit."
)

_SCHEMA_DESCRIPTION_MD = (
    "# Address Parsing & Normalization\n\n"
    "Turn free-form international postal addresses into structured, comparable "
    "data directly in SQL, powered by libpostal.\n\n"
    "## What's here\n\n"
    "- **Parsing** — break a full address string into labeled components, "
    "returned either as a `MAP` or as long-format `(label, value)` rows.\n"
    "- **Component extraction** — pull a single field (city, road, postcode, "
    "state, unit, country, house number) inline in a projection.\n"
    "- **Normalization** — expand abbreviations into canonical forms for fuzzy "
    "matching, joins, and deduplication.\n"
    "- **Discovery** — list the vocabulary of component labels the parser can "
    "emit.\n\n"
    "Output is lower-cased; an empty string yields an empty result and `NULL` "
    "yields `NULL`, so the functions compose cleanly inside larger queries."
)

# VGI506/VGI515: representative, catalog-qualified example queries for the schema,
# each carrying a human-readable description (JSON list of {description, sql}).
_SCHEMA_EXAMPLE_QUERIES = json.dumps(
    [
        {
            "description": "Parse a US address into a MAP of libpostal components.",
            "sql": "SELECT postal.main.parse_address('1600 Pennsylvania Ave NW, Washington, DC 20500')",
        },
        {
            "description": "Pull just the postcode out of a parsed UK address.",
            "sql": "SELECT postal.main.parse_address('10 Downing St, London SW1A 2AA, UK')['postcode']",
        },
        {
            "description": "Normalize an abbreviated address into one expansion per row.",
            "sql": "SELECT UNNEST(postal.main.expand_address('120 E 96th St'))",
        },
        {
            "description": "Extract a single component (the postcode) inline.",
            "sql": "SELECT postal.main.address_postcode('781 Franklin Ave, Brooklyn, NY 11216')",
        },
        {
            "description": "Long-format parse: one (label, value) row per component.",
            "sql": (
                "SELECT label, value FROM postal.main.parse_address_components("
                "'781 Franklin Ave, Brooklyn, NY 11216') ORDER BY label"
            ),
        },
        {
            "description": "List the vocabulary of component labels libpostal can emit.",
            "sql": "SELECT label FROM postal.main.address_labels() ORDER BY label",
        },
    ]
)

# VGI138: vgi.keywords must be a JSON array of strings, not a comma-separated
# string. ``json.dumps`` on these lists yields the required ``["a","b",...]``.
_CATALOG_KEYWORDS = json.dumps(
    [
        "libpostal",
        "address",
        "address parsing",
        "parse address",
        "geocoding",
        "normalization",
        "standardization",
        "postal",
        "postcode",
        "zip",
        "record linkage",
        "deduplication",
        "international addresses",
        "openstreetmap",
    ]
)

_SCHEMA_KEYWORDS = json.dumps(
    [
        "libpostal",
        "address",
        "parse",
        "parse_address",
        "expand_address",
        "components",
        "house_number",
        "road",
        "city",
        "state",
        "postcode",
        "country",
        "unit",
        "labels",
        "normalization",
        "geocoding",
    ]
)

# VGI408-413: the schema's category registry. Categories are the schema's
# navigation/listing sections (and drive SEO); every function/table carries a
# matching `vgi.category` (see `meta.object_tags`). Order here is display order.
_SCHEMA_CATEGORIES = json.dumps(
    [
        {
            "name": "parse",
            "description": (
                "Break a full address string into its labeled components, as a "
                "`MAP` or as long-format (label, value) rows."
            ),
        },
        {
            "name": "extract",
            "description": (
                "Pull a single named component -- city, road, postcode, state, "
                "unit, country, or house number -- out of an address inline."
            ),
        },
        {
            "name": "normalize",
            "description": (
                "Expand and normalize abbreviations into canonical forms for fuzzy matching, joins, and deduplication."
            ),
        },
        {
            "name": "discovery",
            "description": "Discover the vocabulary of component labels libpostal's parser can emit.",
        },
    ]
)

# VGI152/VGI920: a fixed analyst task suite so `vgi-lint simulate` can measure
# how well an agent actually uses this worker. Each `reference_sql` is
# deterministic for a given libpostal model; `ignore_column_names` lets the
# analyst alias result columns freely (values/rows are what's graded).
_AGENT_TEST_TASKS = json.dumps(
    [
        {
            "name": "extract-postcode",
            "prompt": (
                "What postal code does the address '781 Franklin Ave, Brooklyn, "
                "NY 11216' contain? Return just the postcode as a single value."
            ),
            "reference_sql": "SELECT postal.main.address_postcode('781 Franklin Ave, Brooklyn, NY 11216')",
            "ignore_column_names": True,
        },
        {
            "name": "extract-house-number",
            "prompt": (
                "Extract the house (street) number from '1600 Pennsylvania Ave "
                "NW, Washington, DC 20500'. Return it as a single value."
            ),
            "reference_sql": (
                "SELECT postal.main.address_house_number('1600 Pennsylvania Ave NW, Washington, DC 20500')"
            ),
            "ignore_column_names": True,
        },
        {
            "name": "parse-city-from-map",
            "prompt": (
                "Parse '1600 Pennsylvania Ave NW, Washington, DC 20500' into its "
                "address components and return the city."
            ),
            "reference_sql": (
                "SELECT postal.main.parse_address('1600 Pennsylvania Ave NW, Washington, DC 20500')['city']"
            ),
            "ignore_column_names": True,
        },
        {
            "name": "components-road-long-format",
            "prompt": (
                "Using the long-format component parser, what value is labeled "
                "'road' for '781 Franklin Ave, Brooklyn, NY 11216'?"
            ),
            "reference_sql": (
                "SELECT value FROM postal.main.parse_address_components("
                "'781 Franklin Ave, Brooklyn, NY 11216') WHERE label = 'road'"
            ),
            "ignore_column_names": True,
        },
        {
            "name": "count-component-labels",
            "prompt": ("How many distinct address component labels can this worker's discovery function report?"),
            "reference_sql": "SELECT count(*) FROM postal.main.address_labels()",
            "ignore_column_names": True,
        },
        {
            "name": "normalize-contains-expansion",
            "prompt": (
                "When you normalize/expand the abbreviated address '120 E 96th "
                "St', is '120 east 96th street' one of the expansions it "
                "produces? Return a single boolean."
            ),
            "reference_sql": (
                "SELECT list_contains(postal.main.expand_address('120 E 96th St'), '120 east 96th street')"
            ),
            "ignore_column_names": True,
        },
        {
            "name": "extract-road",
            "prompt": (
                "What is the road (street) of the address '781 Franklin Ave, "
                "Brooklyn, NY 11216'? Return just the road as a single value."
            ),
            "reference_sql": "SELECT postal.main.address_road('781 Franklin Ave, Brooklyn, NY 11216')",
            "ignore_column_names": True,
        },
        {
            "name": "extract-state",
            "prompt": (
                "What state/province does the address '781 Franklin Ave, "
                "Brooklyn, NY 11216' contain? Return just the state as a single "
                "value. Note this worker lower-cases its output."
            ),
            "reference_sql": "SELECT postal.main.address_state('781 Franklin Ave, Brooklyn, NY 11216')",
            "ignore_column_names": True,
        },
        {
            "name": "extract-city",
            "prompt": (
                "What is the city of the address '1600 Pennsylvania Ave NW, "
                "Washington, DC 20500'? Return just the city as a single value."
            ),
            "reference_sql": ("SELECT postal.main.address_city('1600 Pennsylvania Ave NW, Washington, DC 20500')"),
            "ignore_column_names": True,
        },
        {
            "name": "extract-unit",
            "prompt": (
                "What is the unit (apartment/suite) of the address 'Apt 5B, 120 "
                "E 96th St, New York, NY 10128'? Return just the unit as a single "
                "value."
            ),
            "reference_sql": ("SELECT postal.main.address_unit('Apt 5B, 120 E 96th St, New York, NY 10128')"),
            "ignore_column_names": True,
        },
        {
            "name": "extract-country",
            "prompt": (
                "What country does the address '10 Downing St, London SW1A 2AA, "
                "United Kingdom' contain? Return just the country as a single "
                "value."
            ),
            "reference_sql": ("SELECT postal.main.address_country('10 Downing St, London SW1A 2AA, United Kingdom')"),
            "ignore_column_names": True,
        },
    ]
)

# VGI311: `address_labels` is a parameterless table function -- it always returns
# the same fixed rows -- so it is ALSO exposed as a regular table that scans that
# function. This lets consumers write `SELECT * FROM postal.main.address_labels`
# (no parentheses), the natural shape for a static discovery set.
_ADDRESS_LABELS_TABLE_DOC_LLM = (
    "## address_labels (table)\n\n"
    "Discovery table listing **every component label libpostal's parser can "
    "emit**, one per row. It is the table form of the `address_labels()` table "
    "function, exposed without parentheses so you can query it as a plain "
    "table (no trailing `()`).\n\n"
    "**Use it when** you need the vocabulary of keys readable out of "
    "`parse_address(...)` or filterable in `parse_address_components(...)` -- "
    "for building a UI, validating a label, or pivoting components into "
    "columns. The set is fixed and deterministic."
)
_ADDRESS_LABELS_TABLE_DOC_MD = (
    "# address_labels\n\n"
    "Discovery table of every component label libpostal can emit, exposed as a "
    "regular table so you can query it as a plain table (no trailing "
    "parentheses).\n\n"
    "## Columns\n\n"
    "- `label` (`VARCHAR`, primary key) -- a component label libpostal can emit "
    "(`road`, `city`, `state`, `postcode`, `country`, `house_number`, `unit`, "
    "...).\n\n"
    "## Usage\n\n"
    "Query it like any table: order the `label` column to browse the full "
    "vocabulary, filter it to validate that a candidate key is one libpostal "
    "recognizes, or count the rows to size the label set. Ready-to-run examples "
    "are carried in this relation's example-query metadata."
)

_DISCOVERY_TABLES: list[Table] = [
    Table(
        name="address_labels",
        function=AddressLabelsFunction,
        comment="Every component label libpostal can emit, one per row (discovery table).",
        primary_key=(("label",),),
        not_null=("label",),
        column_comments={
            "label": "A component label libpostal can emit, e.g. road, city, state, postcode, country.",
        },
        tags={
            "vgi.title": "Address Component Labels Table",
            "vgi.doc_llm": _ADDRESS_LABELS_TABLE_DOC_LLM,
            "vgi.doc_md": _ADDRESS_LABELS_TABLE_DOC_MD,
            # VGI409/VGI411: primary category (from the schema's vgi.categories).
            "vgi.category": "discovery",
            # VGI138: keywords must be a JSON array of strings.
            "vgi.keywords": json.dumps(
                [
                    "labels",
                    "component labels",
                    "discovery",
                    "vocabulary",
                    "fields",
                    "keys",
                    "libpostal",
                    "table",
                ]
            ),
            "domain": "geospatial",
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "List every component label libpostal can emit.",
                        "sql": "SELECT label FROM postal.main.address_labels ORDER BY label",
                    },
                    {
                        "description": "Count how many component labels libpostal recognizes.",
                        "sql": "SELECT count(*) AS label_count FROM postal.main.address_labels",
                    },
                ]
            ),
        },
    ),
]

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
        # VGI152/VGI920: analyst task suite for `vgi-lint simulate`.
        "vgi.agent_test_tasks": _AGENT_TEST_TASKS,
    },
    schemas=[
        Schema(
            name="main",
            comment="libpostal address parsing, component extraction, and normalization functions",
            tags={
                "vgi.title": "Address Parsing & Normalization",
                "vgi.keywords": _SCHEMA_KEYWORDS,
                # VGI139: source_url belongs only on the catalog object, so the
                # schema no longer carries a redundant per-object vgi.source_url.
                "vgi.doc_llm": _SCHEMA_DESCRIPTION_LLM,
                "vgi.doc_md": _SCHEMA_DESCRIPTION_MD,
                # VGI408-413: the category registry every object's vgi.category refers to.
                "vgi.categories": _SCHEMA_CATEGORIES,
                # VGI123 classifying tags -- BARE keys (not vgi.-namespaced).
                "domain": "geospatial",
                "category": "parsing",
                "topic": "address-normalization",
                # VGI506: representative example queries for the schema.
                "vgi.example_queries": _SCHEMA_EXAMPLE_QUERIES,
            },
            tables=list(_DISCOVERY_TABLES),
            functions=list(_FUNCTIONS),
        ),
    ],
)


class LibpostalWorker(Worker):
    """Worker process hosting the ``postal`` catalog."""

    catalog = _POSTAL_CATALOG


def main() -> None:
    """Run the libpostal worker process (stdio or, via flags, HTTP).

    Kicks off libpostal's ~2 GB model load in a background daemon thread so the
    serve loop / ATTACH handshake starts immediately while the cold load happens
    off the critical path; the first parse/expand query then finds the model
    already resident (see ``vgi_libpostal.addresses.warm_up``).
    """
    threading.Thread(target=addresses.warm_up, name="libpostal-warmup", daemon=True).start()
    LibpostalWorker.main()


if __name__ == "__main__":
    main()
