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
    relative_path: str,
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
        relative_path: Retained for call-site documentation of where the object
            is implemented; no longer emitted as a tag (VGI139 keeps
            ``source_url`` on the catalog only).

    Returns:
        A dict of the standard per-object tags.
    """
    _ = relative_path  # implementation link lives on the catalog (VGI139)
    return {
        "vgi.title": title,
        "vgi.doc_llm": doc_llm,
        "vgi.doc_md": doc_md,
        "vgi.keywords": keywords_json(keywords),
    }
