"""Shared per-object discovery / description metadata for the strict vgi-lint profile.

The ``vgi-lint-check`` strict profile expects a fixed set of tags on **every**
function and table object (and richer tags on the catalog and schema). This
module centralizes the conventions so each function only has to supply its own
human-written content:

- ``vgi.title`` (VGI124)        -- human-friendly display name (must not
  normalize-equal the machine name; add an extra descriptive word).
- ``vgi.doc_llm`` (VGI112)      -- a Markdown narrative aimed at an LLM/agent.
- ``vgi.doc_md`` (VGI113)       -- a Markdown narrative aimed at human docs
  (distinct content from ``vgi.doc_llm``).
- ``vgi.keywords`` (VGI126)     -- a JSON array of search terms / synonyms.

``vgi.source_url`` is intentionally **not** set per object (VGI139): the
implementation link belongs only on the catalog object, so per-function /
per-schema ``source_url`` tags would be redundant and are dropped.
"""

from __future__ import annotations

import json


def keywords_json(keywords: list[str]) -> str:
    """Serialize keywords as a JSON array string for the ``vgi.keywords`` tag.

    VGI138 requires ``vgi.keywords`` to be a JSON array of strings (e.g.
    ``["a","b"]``), not a comma-separated string.

    Args:
        keywords: The individual search terms / synonyms for the object.

    Returns:
        A JSON array string suitable for the ``vgi.keywords`` tag value.
    """
    return json.dumps(keywords)


def object_tags(
    *,
    title: str,
    doc_llm: str,
    doc_md: str,
    keywords: list[str],
    category: str,
    relative_path: str,
    example_queries: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    """Build the standard per-object discovery/description tags.

    Args:
        title: Human-friendly display name (``vgi.title``); must not
            normalize-equal the object's machine name.
        doc_llm: Markdown narrative aimed at an LLM/agent (``vgi.doc_llm``).
        doc_md: Markdown narrative aimed at human docs (``vgi.doc_md``);
            distinct content from ``doc_llm``.
        keywords: Search terms / synonyms (``vgi.keywords``), serialized as a
            JSON array of strings (VGI138).
        category: The object's primary ``vgi.category`` (VGI409/VGI411); must
            name one of the categories declared in the schema's
            ``vgi.categories`` registry.
        relative_path: Retained for call-site documentation of where the object
            is implemented; no longer emitted as a tag (VGI139 keeps
            ``source_url`` on the catalog only).
        example_queries: Optional list of ``{"description", "sql"}`` objects
            emitted as ``vgi.example_queries`` (VGI515) so every example carries
            a human-readable description -- the native ``duckdb_functions()``
            examples carrier drops descriptions on the wire.

    Returns:
        A dict of the standard per-object tags.
    """
    _ = relative_path  # implementation link lives on the catalog (VGI139)
    tags = {
        "vgi.title": title,
        "vgi.doc_llm": doc_llm,
        "vgi.doc_md": doc_md,
        "vgi.keywords": keywords_json(keywords),
        # VGI409/VGI411: primary category, drawn from the schema's vgi.categories.
        "vgi.category": category,
    }
    if example_queries is not None:
        # VGI515: described examples ({"description","sql"}), JSON-serialized.
        tags["vgi.example_queries"] = json.dumps(example_queries)
    return tags


# ---------------------------------------------------------------------------
# Composed example queries
#
# Each combines two or more of this worker's own objects in one realistic query.
# They are defined ONCE here and referenced from the schema-level example list
# (worker.py), the example list of the object that drives each query (so the
# vgi-lint agent simulator, which only shows per-object examples, sees them), and
# -- being offline and deterministic for a given libpostal model -- the
# guaranteed-runnable ``vgi.executable_examples`` list. test/sql/composed.test
# pins their output.
# ---------------------------------------------------------------------------

#: expand_address + address_postcode: record-linkage duplicate detection.
COMPOSED_DEDUP_EXAMPLE: dict[str, str] = {
    "description": (
        "Find duplicate customer addresses: block candidate pairs on the extracted "
        "postcode, then match when their libpostal normalized expansions overlap "
        "(pairs 1-2 and 3-4 match; 120 vs 130 E 96th St does not)."
    ),
    "sql": (
        "WITH customers(id, addr) AS (VALUES "
        "(1, '120 E 96th St, New York, NY 10128'), "
        "(2, '120 East 96th Street, New York NY 10128'), "
        "(3, '781 Franklin Ave, Brooklyn, NY 11216'), "
        "(4, '781 Franklin Avenue, Brooklyn NY 11216'), "
        "(5, '130 E 96th St, New York, NY 10128')), "
        "keyed AS (SELECT id, addr, postal.main.address_postcode(addr) AS postcode, "
        "postal.main.expand_address(addr) AS forms FROM customers) "
        "SELECT a.id AS id_a, b.id AS id_b, a.postcode "
        "FROM keyed AS a JOIN keyed AS b "
        "ON a.postcode = b.postcode AND a.id < b.id AND list_has_any(a.forms, b.forms) "
        "ORDER BY id_a, id_b"
    ),
}

#: parse_address_components feeding expand_address: normalize each component.
COMPOSED_NORMALIZE_COMPONENTS_EXAMPLE: dict[str, str] = {
    "description": (
        "Parse an address into long-format components and normalize each value with "
        "expand_address (e.g. road 'pennsylvania ave nw' -> 'pennsylvania avenue "
        "northwest', state 'dc' -> 'district of columbia')."
    ),
    "sql": (
        "SELECT label, value, postal.main.expand_address(value) AS normalized "
        "FROM postal.main.parse_address_components("
        "'1600 Pennsylvania Ave NW, Washington, DC 20500') ORDER BY label"
    ),
}

#: address_labels LEFT JOIN parse_address keys: per-label fill rate of a batch.
COMPOSED_LABEL_COVERAGE_EXAMPLE: dict[str, str] = {
    "description": (
        "Profile a batch of addresses: for every label libpostal can emit, count how "
        "many addresses it was parsed out of (0 for labels none of them contain)."
    ),
    "sql": (
        "WITH addrs(addr) AS (VALUES "
        "('781 Franklin Ave, Brooklyn, NY 11216'), "
        "('Apt 5B, 120 E 96th St, New York, NY 10128'), "
        "('10 Downing St, London SW1A 2AA, United Kingdom')), "
        "found AS (SELECT DISTINCT addr, unnest(map_keys(postal.main.parse_address(addr))) AS label FROM addrs) "
        "SELECT l.label, count(f.addr) AS addresses_with_label "
        "FROM postal.main.address_labels AS l LEFT JOIN found AS f USING (label) "
        "GROUP BY l.label ORDER BY addresses_with_label DESC, l.label"
    ),
}
