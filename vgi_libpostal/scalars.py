"""Per-row scalar libpostal functions.

Every function here is a true DuckDB **scalar** -- one value (per row) in, one
value out -- so it can be used inline in any projection or predicate:

    SELECT parse_address(addr)              FROM places;          -- MAP(VARCHAR, VARCHAR)
    SELECT parse_address(addr)['city']      FROM places;          -- pull one component
    SELECT UNNEST(expand_address(addr))     FROM places;          -- VARCHAR[]
    SELECT address_postcode(addr)           FROM places;          -- VARCHAR

Two shapes of return value need an **explicit Arrow type** on ``Returns`` -- the
SDK cannot infer the element/key-value types of a ``MAP`` or ``LIST`` from the
Python annotation alone (the same requirement ``vgi-calendar`` hit for its
TIMESTAMPTZ scalars):

- ``parse_address``  -> ``Returns(arrow_type=pa.map_(pa.string(), pa.string()))``
- ``expand_address`` -> ``Returns(arrow_type=pa.list_(pa.string()))``

NULL semantics: a NULL input row yields a NULL result (NULL map / NULL list /
NULL string). An **empty string** parses to an empty map / empty list (never an
error). libpostal **lower-cases** its output, so extracted components come back
lower-cased (``address_state('... NY ...') == 'ny'``).

The component extractors (``address_road`` etc.) each return the matching
libpostal component, or NULL when that component is absent from the parse.

The set-returning ``parse_address_components`` / ``address_labels`` functions
are *table functions* and live in :mod:`vgi_libpostal.tables`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import pyarrow as pa
from vgi.arguments import Param, Returns
from vgi.metadata import FunctionExample
from vgi.scalar_function import ScalarFunction

from . import addresses
from .meta import object_tags

_SCALARS_SRC = "vgi_libpostal/scalars.py"

_MAP_TYPE = pa.map_(pa.string(), pa.string())
_LIST_TYPE = pa.list_(pa.string())


# ---------------------------------------------------------------------------
# Small mapping helpers: apply a pure ``str -> X`` function across an array,
# passing NULL straight through.
# ---------------------------------------------------------------------------


def _map_str(arr: pa.StringArray, fn: Callable[[str], str | None]) -> pa.StringArray:
    out = [None if x is None else fn(x) for x in arr.to_pylist()]
    return pa.array(out, type=pa.string())


def _map_map(arr: pa.StringArray, fn: Callable[[str], list[tuple[str, str]]]) -> pa.MapArray:
    out = [None if x is None else fn(x) for x in arr.to_pylist()]
    return pa.array(out, type=_MAP_TYPE)


def _map_list(arr: pa.StringArray, fn: Callable[[str], list[str]]) -> pa.ListArray:
    out = [None if x is None else fn(x) for x in arr.to_pylist()]
    return pa.array(out, type=_LIST_TYPE)


# ===========================================================================
# parse_address -> MAP(VARCHAR, VARCHAR)
# ===========================================================================


class ParseAddressFunction(ScalarFunction):
    """``parse_address(text)`` -- libpostal components as a MAP(label -> value)."""

    class Meta:
        """Function metadata."""

        name = "parse_address"
        description = (
            "Parse an address into a MAP of libpostal components "
            "(road, city, state, postcode, country, house_number, unit, ...). "
            "Values are lower-cased; empty string -> empty map; NULL -> NULL."
        )
        categories = ["libpostal", "parse"]
        tags = object_tags(
            title="Parse Address Into Component Map",
            category="parse",
            doc_llm=(
                "## parse_address\n\n"
                "Parse a single free-form postal address string into a "
                "`MAP(VARCHAR, VARCHAR)` of libpostal components, keyed by the "
                "component label libpostal assigns (`house_number`, `road`, "
                "`unit`, `city`, `state`, `postcode`, `country`, and more).\n\n"
                "**Use it when** you have unstructured address text and need it "
                "broken into addressable fields for geocoding pre-processing, "
                "standardization, deduplication, or record linkage -- all inline "
                "in SQL.\n\n"
                "**Input:** one `VARCHAR` address per row. **Output:** a "
                "`MAP(VARCHAR, VARCHAR)`. Index a single field with "
                "`parse_address(addr)['city']`.\n\n"
                "**Behaviors / edge cases:** libpostal is a statistical "
                "(OSM-trained) parser, so labels are best-effort and occasionally "
                "surprising (a borough may come back as `city_district`, not "
                "`city`). All values are **lower-cased**. An empty string parses "
                "to an empty map (not an error); a `NULL` input yields `NULL`. "
                "For the long-format `(label, value)` row shape, use the "
                "`parse_address_components` table function instead."
            ),
            doc_md=(
                "# parse_address\n\n"
                "Parse a free-form postal address into a "
                "`MAP(VARCHAR, VARCHAR)` of libpostal components.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT postal.main.parse_address('1600 Pennsylvania Ave NW, Washington, DC 20500');\n"
                "SELECT postal.main.parse_address('10 Downing St, London SW1A 2AA, UK')['postcode'];\n"
                "```\n\n"
                "## Notes\n\n"
                "- Keys are libpostal labels (`house_number`, `road`, `unit`, "
                "`city`, `state`, `postcode`, `country`, ...).\n"
                "- Values are lower-cased; an empty string yields an empty map "
                "and `NULL` yields `NULL`.\n"
                "- Labels are statistical and may vary across address styles; see "
                "`address_labels()` for the full label set."
            ),
            keywords=[
                "parse address",
                "address parser",
                "libpostal",
                "components",
                "map",
                "house number",
                "road",
                "street",
                "city",
                "state",
                "postcode",
                "zip",
                "country",
                "geocoding",
                "standardization",
                "record linkage",
            ],
            relative_path=_SCALARS_SRC,
            example_queries=[
                {
                    "description": "Parse a US address into a component MAP.",
                    "sql": "SELECT postal.main.parse_address('1600 Pennsylvania Ave NW, Washington, DC 20500')",
                },
                {
                    "description": "Pull the postcode out of the parsed map.",
                    "sql": "SELECT postal.main.parse_address('10 Downing St, London SW1A 2AA, UK')['postcode']",
                },
            ],
        )
        examples = [
            FunctionExample(
                sql="SELECT postal.main.parse_address('1600 Pennsylvania Ave NW, Washington, DC 20500')",
                description="Parse a US address into components",
            ),
            FunctionExample(
                sql="SELECT postal.main.parse_address('10 Downing St, London SW1A 2AA, UK')['postcode']",
                description="Pull the postcode out of the parsed map",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Address text to parse.")]
    ) -> Annotated[pa.MapArray, Returns(arrow_type=_MAP_TYPE)]:
        """Parse each row into a MAP of libpostal components (NULL passes through)."""
        return _map_map(text, addresses.parse_address_pairs)


# ===========================================================================
# expand_address -> VARCHAR[]
# ===========================================================================


class ExpandAddressFunction(ScalarFunction):
    """``expand_address(text)`` -- normalized expansions as a VARCHAR[] list."""

    class Meta:
        """Function metadata."""

        name = "expand_address"
        description = (
            "Normalize an address into a LIST of libpostal expansions "
            "(e.g. 'St' -> 'street', 'E' -> 'east'). Empty string -> empty list; NULL -> NULL."
        )
        categories = ["libpostal", "expand"]
        tags = object_tags(
            title="Expand Address Abbreviations",
            category="normalize",
            doc_llm=(
                "## expand_address\n\n"
                "Normalize a single address string into a `VARCHAR[]` of "
                "libpostal **expansions** -- canonical, fully-spelled-out forms "
                "where abbreviations and tokens are rewritten (`St` -> `street`, "
                "`E` -> `east`, `Ave` -> `avenue`).\n\n"
                "**Use it when** you need to compare or deduplicate addresses that "
                "are written inconsistently. libpostal may return several equally "
                "valid normalizations (e.g. `st` could mean `street` or `saint`), "
                "so the result is a *list*; match two addresses if their expansion "
                "lists intersect.\n\n"
                "**Input:** one `VARCHAR` address per row. **Output:** a "
                "`VARCHAR[]` of normalized strings. Use `UNNEST(...)` to get one "
                "expansion per row.\n\n"
                "**Behaviors / edge cases:** output is lower-cased. An empty "
                "string yields an empty list (not an error); a `NULL` input "
                "yields `NULL`. This is normalization for matching -- it does not "
                "split the address into fields; use `parse_address` for that."
            ),
            doc_md=(
                "# expand_address\n\n"
                "Normalize an address into a `VARCHAR[]` of libpostal expansions, "
                "rewriting abbreviations into canonical forms for matching and "
                "deduplication.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT postal.main.expand_address('120 E 96th St');\n"
                "SELECT UNNEST(postal.main.expand_address('120 E 96th St'));\n"
                "```\n\n"
                "## Notes\n\n"
                "- Multiple expansions can be returned for an ambiguous token.\n"
                "- Output is lower-cased; an empty string yields an empty list "
                "and `NULL` yields `NULL`.\n"
                "- For field extraction (not normalization), use `parse_address`."
            ),
            keywords=[
                "expand address",
                "normalize",
                "normalization",
                "abbreviation",
                "expansion",
                "libpostal",
                "deduplication",
                "dedupe",
                "record linkage",
                "matching",
                "canonical form",
                "street",
                "saint",
            ],
            relative_path=_SCALARS_SRC,
            example_queries=[
                {
                    "description": "Normalized expansions of an abbreviated address.",
                    "sql": "SELECT postal.main.expand_address('120 E 96th St')",
                },
                {
                    "description": "One normalized expansion per row.",
                    "sql": "SELECT UNNEST(postal.main.expand_address('120 E 96th St'))",
                },
            ],
        )
        examples = [
            FunctionExample(
                sql="SELECT postal.main.expand_address('120 E 96th St')",
                description="Normalized expansions of an abbreviated address",
            ),
            FunctionExample(
                sql="SELECT UNNEST(postal.main.expand_address('120 E 96th St'))",
                description="One expansion per row",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Address text to normalize.")]
    ) -> Annotated[pa.ListArray, Returns(arrow_type=_LIST_TYPE)]:
        """Normalize each row into a LIST of libpostal expansions (NULL passes through)."""
        return _map_list(text, addresses.expand_address)


# ===========================================================================
# Component extractors -> VARCHAR (NULL if that component is absent)
#
# Each pulls one libpostal label out of the parse. They share the same tiny
# body (``_map_str`` over ``address_component``); the per-class ``_LABEL`` names
# which component to read. Kept as explicit classes (not a factory) to match the
# sibling-worker convention and stay mypy-clean.
# ===========================================================================


class AddressHouseNumberFunction(ScalarFunction):
    """``address_house_number(text)`` -- the 'house_number' component, or NULL."""

    _LABEL = "house_number"

    class Meta:
        """Function metadata."""

        name = "address_house_number"
        description = "The libpostal 'house_number' component of an address, or NULL if absent"
        categories = ["libpostal", "extract"]
        tags = object_tags(
            title="Extract House Number Component",
            category="extract",
            doc_llm=(
                "## address_house_number\n\n"
                "Convenience scalar that parses an address with libpostal and "
                "returns just the **`house_number`** component (the street "
                "number), or `NULL` when libpostal does not identify one.\n\n"
                "**Use it when** you only need the street number and want to avoid "
                "indexing a full `parse_address` map. Equivalent to "
                "`parse_address(addr)['house_number']`.\n\n"
                "**Input:** one `VARCHAR` address per row. **Output:** a "
                "`VARCHAR` (lower-cased) or `NULL`. A `NULL` input yields `NULL`; "
                "an address with no detectable house number yields `NULL`."
            ),
            doc_md=(
                "# address_house_number\n\n"
                "Return the libpostal `house_number` (street number) component of "
                "an address.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT postal.main.address_house_number('781 Franklin Ave, Brooklyn, NY 11216');  -- 781\n"
                "```\n\n"
                "## Notes\n\n"
                "Returns `NULL` when no house number is detected and for `NULL` "
                "input. Shorthand for `parse_address(addr)['house_number']`."
            ),
            keywords=[
                "house number",
                "street number",
                "building number",
                "address component",
                "libpostal",
                "extract",
                "parse",
            ],
            relative_path=_SCALARS_SRC,
            example_queries=[
                {
                    "description": "Extract just the house (street) number from an address.",
                    "sql": "SELECT postal.main.address_house_number('781 Franklin Ave, Brooklyn, NY 11216')",
                },
            ],
        )
        examples = [
            FunctionExample(
                sql="SELECT postal.main.address_house_number('781 Franklin Ave, Brooklyn, NY 11216')",
                description="House number of an address",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Address text to parse.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Extract this function's libpostal component for each row (NULL passes through)."""
        return _map_str(text, lambda x: addresses.address_component(x, cls._LABEL))


class AddressRoadFunction(ScalarFunction):
    """``address_road(text)`` -- the 'road' (street) component, or NULL."""

    _LABEL = "road"

    class Meta:
        """Function metadata."""

        name = "address_road"
        description = "The libpostal 'road' (street) component of an address, or NULL if absent"
        categories = ["libpostal", "extract"]
        tags = object_tags(
            title="Extract Road Street Component",
            category="extract",
            doc_llm=(
                "## address_road\n\n"
                "Convenience scalar that parses an address with libpostal and "
                "returns just the **`road`** component (the street name), or "
                "`NULL` when libpostal does not identify one.\n\n"
                "**Use it when** you only need the street name. Equivalent to "
                "`parse_address(addr)['road']`. The `road` label is one of the "
                "most stable libpostal components across address styles.\n\n"
                "**Input:** one `VARCHAR` address per row. **Output:** a "
                "`VARCHAR` (lower-cased) or `NULL`. A `NULL` input yields `NULL`."
            ),
            doc_md=(
                "# address_road\n\n"
                "Return the libpostal `road` (street name) component of an "
                "address.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT postal.main.address_road('781 Franklin Ave, Brooklyn, NY 11216');  -- franklin ave\n"
                "```\n\n"
                "## Notes\n\n"
                "Output is lower-cased. Returns `NULL` when no road is detected "
                "and for `NULL` input. Shorthand for `parse_address(addr)['road']`."
            ),
            keywords=[
                "road",
                "street",
                "street name",
                "thoroughfare",
                "address component",
                "libpostal",
                "extract",
                "parse",
            ],
            relative_path=_SCALARS_SRC,
            example_queries=[
                {
                    "description": "Extract just the road (street name) from an address.",
                    "sql": "SELECT postal.main.address_road('781 Franklin Ave, Brooklyn, NY 11216')",
                },
            ],
        )
        examples = [
            FunctionExample(
                sql="SELECT postal.main.address_road('781 Franklin Ave, Brooklyn, NY 11216')",
                description="Street (road) of an address",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Address text to parse.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Extract this function's libpostal component for each row (NULL passes through)."""
        return _map_str(text, lambda x: addresses.address_component(x, cls._LABEL))


class AddressUnitFunction(ScalarFunction):
    """``address_unit(text)`` -- the 'unit' (apt/suite) component, or NULL."""

    _LABEL = "unit"

    class Meta:
        """Function metadata."""

        name = "address_unit"
        description = "The libpostal 'unit' (apartment/suite) component of an address, or NULL if absent"
        categories = ["libpostal", "extract"]
        tags = object_tags(
            title="Extract Unit Apartment Component",
            category="extract",
            doc_llm=(
                "## address_unit\n\n"
                "Convenience scalar that parses an address with libpostal and "
                "returns just the **`unit`** component (apartment, suite, floor, "
                "or similar sub-address), or `NULL` when libpostal does not "
                "identify one.\n\n"
                "**Use it when** you need the secondary/sub-premise designator. "
                "Equivalent to `parse_address(addr)['unit']`. Many addresses have "
                "no unit, so `NULL` is common and expected.\n\n"
                "**Input:** one `VARCHAR` address per row. **Output:** a "
                "`VARCHAR` (lower-cased) or `NULL`. A `NULL` input yields `NULL`."
            ),
            doc_md=(
                "# address_unit\n\n"
                "Return the libpostal `unit` (apartment / suite / floor) component "
                "of an address.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT postal.main.address_unit('Apt 5B, 120 E 96th St, New York, NY 10128');  -- apt 5b\n"
                "```\n\n"
                "## Notes\n\n"
                "`NULL` is common -- most addresses have no unit. Returns `NULL` "
                "for `NULL` input. Shorthand for `parse_address(addr)['unit']`."
            ),
            keywords=[
                "unit",
                "apartment",
                "apt",
                "suite",
                "floor",
                "sub-premise",
                "secondary address",
                "address component",
                "libpostal",
                "extract",
                "parse",
            ],
            relative_path=_SCALARS_SRC,
            example_queries=[
                {
                    "description": "Extract the unit (apartment/suite) from an address.",
                    "sql": "SELECT postal.main.address_unit('Apt 5B, 120 E 96th St, New York, NY 10128')",
                },
            ],
        )
        examples = [
            FunctionExample(
                sql="SELECT postal.main.address_unit('Apt 5B, 120 E 96th St, New York, NY 10128')",
                description="Unit / apartment of an address",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Address text to parse.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Extract this function's libpostal component for each row (NULL passes through)."""
        return _map_str(text, lambda x: addresses.address_component(x, cls._LABEL))


class AddressCityFunction(ScalarFunction):
    """``address_city(text)`` -- the 'city' component, or NULL."""

    _LABEL = "city"

    class Meta:
        """Function metadata."""

        name = "address_city"
        description = "The libpostal 'city' component of an address, or NULL if absent"
        categories = ["libpostal", "extract"]
        tags = object_tags(
            title="Extract City Locality Component",
            category="extract",
            doc_llm=(
                "## address_city\n\n"
                "Convenience scalar that parses an address with libpostal and "
                "returns just the **`city`** component (the locality), or `NULL` "
                "when libpostal does not identify one.\n\n"
                "**Use it when** you need just the city/town. Equivalent to "
                "`parse_address(addr)['city']`.\n\n"
                "**Caveat:** libpostal is statistical and may tag a borough or "
                "district as `city_district` or a neighbourhood as `suburb` "
                "rather than `city` (e.g. *Brooklyn* often comes back as "
                "`city_district`, not `city`). For such inputs this function "
                "returns `NULL`; inspect `parse_address(addr)` to see the full "
                "label set.\n\n"
                "**Input:** one `VARCHAR` address per row. **Output:** a "
                "`VARCHAR` (lower-cased) or `NULL`. A `NULL` input yields `NULL`."
            ),
            doc_md=(
                "# address_city\n\n"
                "Return the libpostal `city` (locality) component of an "
                "address.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT postal.main.address_city('1600 Pennsylvania Ave NW, Washington, DC 20500');  -- washington\n"
                "```\n\n"
                "## Notes\n\n"
                "libpostal may classify boroughs/districts as `city_district` and "
                "neighbourhoods as `suburb` rather than `city`, in which case this "
                "returns `NULL`. Shorthand for `parse_address(addr)['city']`."
            ),
            keywords=[
                "city",
                "town",
                "locality",
                "municipality",
                "place",
                "address component",
                "libpostal",
                "extract",
                "parse",
            ],
            relative_path=_SCALARS_SRC,
            example_queries=[
                {
                    "description": "Extract just the city (locality) from an address.",
                    "sql": "SELECT postal.main.address_city('1600 Pennsylvania Ave NW, Washington, DC 20500')",
                },
            ],
        )
        examples = [
            FunctionExample(
                sql="SELECT postal.main.address_city('1600 Pennsylvania Ave NW, Washington, DC 20500')",
                description="City of an address",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Address text to parse.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Extract this function's libpostal component for each row (NULL passes through)."""
        return _map_str(text, lambda x: addresses.address_component(x, cls._LABEL))


class AddressStateFunction(ScalarFunction):
    """``address_state(text)`` -- the 'state' (province/region) component, or NULL."""

    _LABEL = "state"

    class Meta:
        """Function metadata."""

        name = "address_state"
        description = "The libpostal 'state' (province/region) component of an address, or NULL if absent"
        categories = ["libpostal", "extract"]
        tags = object_tags(
            title="Extract State Province Component",
            category="extract",
            doc_llm=(
                "## address_state\n\n"
                "Convenience scalar that parses an address with libpostal and "
                "returns just the **`state`** component (state, province, or "
                "region), or `NULL` when libpostal does not identify one.\n\n"
                "**Use it when** you need the first-level administrative division. "
                "Equivalent to `parse_address(addr)['state']`.\n\n"
                "**Input:** one `VARCHAR` address per row. **Output:** a "
                "`VARCHAR` (lower-cased) or `NULL`. Note libpostal lower-cases "
                "output, so a US state abbreviation comes back as e.g. `ny`, not "
                "`NY`. A `NULL` input yields `NULL`."
            ),
            doc_md=(
                "# address_state\n\n"
                "Return the libpostal `state` (state / province / region) "
                "component of an address.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT postal.main.address_state('781 Franklin Ave, Brooklyn, NY 11216');  -- ny\n"
                "```\n\n"
                "## Notes\n\n"
                "Output is lower-cased (`NY` -> `ny`). Returns `NULL` when no "
                "state is detected and for `NULL` input. Shorthand for "
                "`parse_address(addr)['state']`."
            ),
            keywords=[
                "state",
                "province",
                "region",
                "administrative area",
                "address component",
                "libpostal",
                "extract",
                "parse",
            ],
            relative_path=_SCALARS_SRC,
            example_queries=[
                {
                    "description": "Extract the state/province from an address (output is lower-cased).",
                    "sql": "SELECT postal.main.address_state('781 Franklin Ave, Brooklyn, NY 11216')",
                },
            ],
        )
        examples = [
            FunctionExample(
                sql="SELECT postal.main.address_state('781 Franklin Ave, Brooklyn, NY 11216')",
                description="State / province of an address",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Address text to parse.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Extract this function's libpostal component for each row (NULL passes through)."""
        return _map_str(text, lambda x: addresses.address_component(x, cls._LABEL))


class AddressPostcodeFunction(ScalarFunction):
    """``address_postcode(text)`` -- the 'postcode' (ZIP) component, or NULL."""

    _LABEL = "postcode"

    class Meta:
        """Function metadata."""

        name = "address_postcode"
        description = "The libpostal 'postcode' (ZIP) component of an address, or NULL if absent"
        categories = ["libpostal", "extract"]
        tags = object_tags(
            title="Extract Postcode ZIP Component",
            category="extract",
            doc_llm=(
                "## address_postcode\n\n"
                "Convenience scalar that parses an address with libpostal and "
                "returns just the **`postcode`** component (ZIP / postal code), or "
                "`NULL` when libpostal does not identify one.\n\n"
                "**Use it when** you need just the postal code -- e.g. to bucket "
                "addresses by ZIP for geocoding or analytics. Equivalent to "
                "`parse_address(addr)['postcode']`.\n\n"
                "**Input:** one `VARCHAR` address per row. **Output:** a "
                "`VARCHAR` (lower-cased) or `NULL`. A `NULL` input yields `NULL`."
            ),
            doc_md=(
                "# address_postcode\n\n"
                "Return the libpostal `postcode` (ZIP / postal code) component of "
                "an address.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT postal.main.address_postcode('781 Franklin Ave, Brooklyn, NY 11216');  -- 11216\n"
                "```\n\n"
                "## Notes\n\n"
                "Returns `NULL` when no postcode is detected and for `NULL` input. "
                "Shorthand for `parse_address(addr)['postcode']`."
            ),
            keywords=[
                "postcode",
                "postal code",
                "zip",
                "zip code",
                "zipcode",
                "address component",
                "libpostal",
                "extract",
                "parse",
            ],
            relative_path=_SCALARS_SRC,
            example_queries=[
                {
                    "description": "Extract just the postcode (ZIP) from an address.",
                    "sql": "SELECT postal.main.address_postcode('781 Franklin Ave, Brooklyn, NY 11216')",
                },
            ],
        )
        examples = [
            FunctionExample(
                sql="SELECT postal.main.address_postcode('781 Franklin Ave, Brooklyn, NY 11216')",
                description="Postal code of an address",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Address text to parse.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Extract this function's libpostal component for each row (NULL passes through)."""
        return _map_str(text, lambda x: addresses.address_component(x, cls._LABEL))


class AddressCountryFunction(ScalarFunction):
    """``address_country(text)`` -- the 'country' component, or NULL."""

    _LABEL = "country"

    class Meta:
        """Function metadata."""

        name = "address_country"
        description = "The libpostal 'country' component of an address, or NULL if absent"
        categories = ["libpostal", "extract"]
        tags = object_tags(
            title="Extract Country Component",
            category="extract",
            doc_llm=(
                "## address_country\n\n"
                "Convenience scalar that parses an address with libpostal and "
                "returns just the **`country`** component, or `NULL` when "
                "libpostal does not identify one.\n\n"
                "**Use it when** you need only the country. Equivalent to "
                "`parse_address(addr)['country']`. Note many addresses omit the "
                "country (it is implied), in which case this returns `NULL`.\n\n"
                "**Input:** one `VARCHAR` address per row. **Output:** a "
                "`VARCHAR` (lower-cased) or `NULL`. A `NULL` input yields `NULL`."
            ),
            doc_md=(
                "# address_country\n\n"
                "Return the libpostal `country` component of an address.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT postal.main.address_country('10 Downing St, London SW1A 2AA, United Kingdom');\n"
                "```\n\n"
                "## Notes\n\n"
                "Returns `NULL` when the country is absent or implied, and for "
                "`NULL` input. Shorthand for `parse_address(addr)['country']`."
            ),
            keywords=[
                "country",
                "nation",
                "address component",
                "libpostal",
                "extract",
                "parse",
                "international",
            ],
            relative_path=_SCALARS_SRC,
            example_queries=[
                {
                    "description": "Extract the country from an international address.",
                    "sql": "SELECT postal.main.address_country('10 Downing St, London SW1A 2AA, United Kingdom')",
                },
            ],
        )
        examples = [
            FunctionExample(
                sql="SELECT postal.main.address_country('10 Downing St, London SW1A 2AA, United Kingdom')",
                description="Country of an address",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Address text to parse.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Extract this function's libpostal component for each row (NULL passes through)."""
        return _map_str(text, lambda x: addresses.address_component(x, cls._LABEL))


SCALAR_FUNCTIONS: list[type] = [
    ParseAddressFunction,
    ExpandAddressFunction,
    AddressHouseNumberFunction,
    AddressRoadFunction,
    AddressUnitFunction,
    AddressCityFunction,
    AddressStateFunction,
    AddressPostcodeFunction,
    AddressCountryFunction,
]
