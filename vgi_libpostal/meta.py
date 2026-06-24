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
- ``vgi.keywords`` (VGI126)     -- comma-separated search terms / synonyms.
- ``vgi.source_url`` (VGI128)   -- link to the implementing source file.

``source_url(path)`` builds the canonical GitHub blob URL for a source file so
every object points at exactly where it is implemented.
"""

from __future__ import annotations

#: Base GitHub blob URL for source files in this repo (pinned to ``main``).
SOURCE_BASE = "https://github.com/Query-farm/vgi-libpostal/blob/main"


def source_url(relative_path: str) -> str:
    """Build the implementation ``vgi.source_url`` for a repo-relative file.

    Args:
        relative_path: Path to the implementing file relative to the repo root,
            e.g. ``"vgi_libpostal/scalars.py"``.

    Returns:
        The canonical GitHub blob URL (pinned to ``main``) for that file.
    """
    return f"{SOURCE_BASE}/{relative_path}"


def object_tags(
    *,
    title: str,
    doc_llm: str,
    doc_md: str,
    keywords: str,
    relative_path: str,
) -> dict[str, str]:
    """Build the five standard per-object discovery/description tags.

    Args:
        title: Human-friendly display name (``vgi.title``); must not
            normalize-equal the object's machine name.
        doc_llm: Markdown narrative aimed at an LLM/agent (``vgi.doc_llm``).
        doc_md: Markdown narrative aimed at human docs (``vgi.doc_md``);
            distinct content from ``doc_llm``.
        keywords: Comma-separated search terms / synonyms (``vgi.keywords``).
        relative_path: Implementing file relative to the repo root, used to
            build ``vgi.source_url``.

    Returns:
        A dict of the five standard per-object tags.
    """
    return {
        "vgi.title": title,
        "vgi.doc_llm": doc_llm,
        "vgi.doc_md": doc_md,
        "vgi.keywords": keywords,
        "vgi.source_url": source_url(relative_path),
    }
