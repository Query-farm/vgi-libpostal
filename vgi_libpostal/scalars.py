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
        examples = [
            FunctionExample(
                sql="SELECT postal.parse_address('1600 Pennsylvania Ave NW, Washington, DC 20500')",
                description="Parse a US address into components",
            ),
            FunctionExample(
                sql="SELECT postal.parse_address('10 Downing St, London SW1A 2AA, UK')['postcode']",
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
        examples = [
            FunctionExample(
                sql="SELECT postal.expand_address('120 E 96th St')",
                description="Normalized expansions of an abbreviated address",
            ),
            FunctionExample(
                sql="SELECT UNNEST(postal.expand_address('120 E 96th St'))",
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
        examples = [
            FunctionExample(
                sql="SELECT postal.address_house_number('781 Franklin Ave, Brooklyn, NY 11216')",
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
        examples = [
            FunctionExample(
                sql="SELECT postal.address_road('781 Franklin Ave, Brooklyn, NY 11216')",
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
        examples = [
            FunctionExample(
                sql="SELECT postal.address_unit('Apt 5B, 120 E 96th St, New York, NY 10128')",
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
        examples = [
            FunctionExample(
                sql="SELECT postal.address_city('1600 Pennsylvania Ave NW, Washington, DC 20500')",
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
        examples = [
            FunctionExample(
                sql="SELECT postal.address_state('781 Franklin Ave, Brooklyn, NY 11216')",
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
        examples = [
            FunctionExample(
                sql="SELECT postal.address_postcode('781 Franklin Ave, Brooklyn, NY 11216')",
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
        examples = [
            FunctionExample(
                sql="SELECT postal.address_country('10 Downing St, London SW1A 2AA, United Kingdom')",
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
