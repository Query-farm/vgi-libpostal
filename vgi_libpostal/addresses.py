"""Pure address parsing + normalization logic over libpostal (pypostal).

No Arrow or VGI dependency lives here -- every function takes and returns plain
Python objects, so the logic is directly unit-testable without spawning a
worker. The Arrow/VGI wrappers live in :mod:`vgi_libpostal.scalars` and
:mod:`vgi_libpostal.tables`.

This module is a thin, deterministic adapter over the ``postal`` binding:

- :func:`parse_address_map` -> ``dict[label, value]`` (libpostal components)
- :func:`parse_address_pairs` -> ``list[(label, value)]`` (long / one-per-row)
- :func:`expand_address` -> ``list[str]`` (normalized expansions)
- :func:`address_component` -> a single component value, or ``None``

Notes on libpostal behaviour that the rest of the codebase relies on:

- **Output is lower-cased.** libpostal normalises to lower case, so
  ``parse_address_map("Brooklyn NY")["state"] == "ny"`` (not ``"NY"``). Tests
  assert against lower case.
- **Empty input is not an error.** ``parse_address("")`` returns ``[]``; we map
  that to an empty dict / no rows (never an exception).
- libpostal can emit a component **label more than once** for one address. We
  keep the **last** occurrence in the map (dict semantics); the long-format
  :func:`parse_address_pairs` preserves every pair in order.

The full set of component labels libpostal can emit is :data:`COMPONENT_LABELS`.
"""

from __future__ import annotations

from postal.expand import expand_address as _expand_address
from postal.parser import parse_address as _parse_address

# The component labels libpostal's address parser can emit. This is the model's
# documented tag set (libpostal >= 1.1). Exposed via the ``address_labels()``
# discovery table function and used to validate the convenience extractors.
COMPONENT_LABELS: tuple[str, ...] = (
    "house",  # venue / building name (e.g. "fred's auto repair")
    "category",  # for category queries (e.g. "restaurants")
    "near",  # phrases like "in", "near"
    "house_number",  # usually number portion of a street address
    "road",  # street name(s)
    "unit",  # apartment, suite, lot, etc.
    "level",  # floor number
    "staircase",  # stairwell number
    "entrance",  # entrance number / letter
    "po_box",  # post office box
    "postcode",  # postal code / ZIP
    "suburb",  # neighbourhood / informal sub-city
    "city_district",  # borough / administrative division of a city
    "city",  # city / town / village
    "island",  # named island
    "state_district",  # administrative division within a state
    "state",  # state / province / region
    "country_region",  # informal country sub-region
    "country",  # country
    "world_region",  # macro-region (e.g. "central america")
)


def parse_address_pairs(text: str | None) -> list[tuple[str, str]]:
    """Parse ``text`` into ``(label, value)`` pairs, in libpostal's order.

    Returns an empty list for ``None`` or an empty/whitespace-only string.
    Values are libpostal's (lower-cased) component strings.
    """
    if text is None:
        return []
    text = text.strip()
    if not text:
        return []
    # libpostal returns (value, label); flip to (label, value) for our API.
    return [(label, value) for (value, label) in _parse_address(text)]


def parse_address_map(text: str | None) -> dict[str, str]:
    """Parse ``text`` into a ``{label: value}`` map of libpostal components.

    Returns an empty dict for ``None`` or an empty string. If libpostal emits a
    label more than once, the last occurrence wins (plain dict semantics);
    :func:`parse_address_pairs` preserves every pair if you need them all.
    """
    return dict(parse_address_pairs(text))


def address_component(text: str | None, label: str) -> str | None:
    """Return a single parsed component (e.g. ``"road"``), or ``None`` if absent."""
    return parse_address_map(text).get(label)


def expand_address(text: str | None) -> list[str]:
    """Return libpostal's normalized expansions of ``text``.

    Each expansion is a fully normalised string (e.g. ``"st"`` -> ``"street"``,
    ``"e"`` -> ``"east"``). Returns an empty list for ``None`` or empty input.
    """
    if text is None:
        return []
    text = text.strip()
    if not text:
        return []
    return list(_expand_address(text))
