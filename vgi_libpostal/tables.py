"""Set-returning libpostal table functions for DuckDB.

These expand to **many rows**, so they are exposed as **table functions** -- the
form that accepts DuckDB positional / ``name := value`` arguments. The per-row,
single-value functions (``parse_address`` MAP, ``expand_address`` LIST, the
``address_*`` extractors) are *scalars* and live in
:mod:`vgi_libpostal.scalars`, so they can be used inline in a projection.

    SELECT * FROM postal.parse_address_components('781 Franklin Ave, Brooklyn, NY 11216');
    SELECT * FROM postal.address_labels() ORDER BY label;

``parse_address_components`` is the long-format complement to the
``parse_address`` MAP scalar: one ``(label, value)`` row per parsed component,
in libpostal's order. ``address_labels`` is pure discovery -- the set of
component labels libpostal can emit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, ClassVar

import pyarrow as pa
from vgi.arguments import Arg
from vgi.metadata import FunctionExample
from vgi.table_function import (
    BindParams,
    ProcessParams,
    TableCardinality,
    TableFunctionGenerator,
    bind_fixed_schema,
    init_single_worker,
)
from vgi_rpc.rpc import OutputCollector

from . import addresses
from .meta import object_tags
from .schema_utils import field

_TABLES_SRC = "vgi_libpostal/tables.py"

# VGI509: guaranteed-runnable, catalog-qualified executable examples. Each `sql`
# is self-contained and re-runnable against an attached `postal` worker. We omit
# `expected_result` deliberately -- the linter only needs each query to execute
# cleanly, and libpostal output is statistical/lower-cased, so pinning exact
# values would be brittle.
_EXECUTABLE_EXAMPLES = (
    "["
    '{"description": "Parse a US address into a component MAP.",'
    ' "sql": "SELECT postal.main.parse_address('
    "'1600 Pennsylvania Ave NW, Washington, DC 20500')\"},"
    '{"description": "Pull one component out of the parsed map.",'
    ' "sql": "SELECT postal.main.parse_address('
    "'10 Downing St, London SW1A 2AA, UK')['postcode']\"},"
    '{"description": "Normalize/expand an abbreviated address for matching.",'
    ' "sql": "SELECT postal.main.expand_address(\'120 E 96th St\')"},'
    '{"description": "Extract just the postcode from an address.",'
    ' "sql": "SELECT postal.main.address_postcode('
    "'781 Franklin Ave, Brooklyn, NY 11216')\"},"
    '{"description": "Long-format parse: one (label, value) row per component.",'
    ' "sql": "SELECT * FROM postal.main.parse_address_components('
    "'781 Franklin Ave, Brooklyn, NY 11216')\"},"
    '{"description": "List the component labels libpostal can emit.",'
    ' "sql": "SELECT label FROM postal.main.address_labels() ORDER BY label"}'
    "]"
)


@dataclass(kw_only=True)
class _ParseComponentsArgs:
    """``parse_address_components(text)``."""

    text: Annotated[str, Arg(0, arrow_type=pa.string(), doc="Address text to parse.")]


_PARSE_COMPONENTS_SCHEMA = pa.schema(
    [
        field("label", pa.string(), "libpostal component label (road, city, ...).", nullable=False),
        field("value", pa.string(), "The (lower-cased) component value.", nullable=False),
    ]
)


@init_single_worker
@bind_fixed_schema
class ParseAddressComponentsFunction(TableFunctionGenerator[_ParseComponentsArgs]):
    """Parse an address into one ``(label, value)`` row per component.

    The long-format complement to the ``parse_address`` MAP scalar. Empty /
    whitespace input yields no rows (not an error).
    """

    FIXED_SCHEMA: ClassVar[pa.Schema] = _PARSE_COMPONENTS_SCHEMA

    class Meta:
        """Function metadata."""

        name = "parse_address_components"
        description = "Parse an address into one (label, value) row per libpostal component"
        categories = ["libpostal", "parse"]
        tags = {
            **object_tags(
                title="Parse Address Components Long Format",
                category="parse",
                doc_llm=(
                    "## parse_address_components\n\n"
                    "Table function: parse a single address string and emit one "
                    "`(label, value)` **row per libpostal component**, in "
                    "libpostal's order. This is the long-format complement to the "
                    "`parse_address` MAP scalar.\n\n"
                    "**Use it when** you want to filter, join, or aggregate over "
                    "address components in set-based SQL (e.g. "
                    "`... WHERE label = 'city'`) rather than indexing a map.\n\n"
                    "**Argument:** `text` (`VARCHAR`) -- the address to parse. "
                    "**Returns:** rows of `(label VARCHAR, value VARCHAR)`.\n\n"
                    "**Behaviors / edge cases:** values are lower-cased; labels "
                    "are statistical and best-effort (see `address_labels()` for "
                    "the full set). An empty / whitespace input yields **no rows** "
                    "(not an error)."
                ),
                doc_md=(
                    "# parse_address_components\n\n"
                    "Parse an address into one `(label, value)` row per libpostal "
                    "component -- the long-format complement to the "
                    "`parse_address` MAP scalar.\n\n"
                    "## Result\n\n"
                    "Each returned row pairs a libpostal component `label` (such as "
                    "`house_number`, `road`, `city`, `state`, or `postcode`) with "
                    "its lower-cased `value`, in libpostal's own token order. "
                    "Because it is a table function, you consume it in the `FROM` "
                    "clause and can freely filter, join, or aggregate the component "
                    "rows -- for example keeping only the `city` label, or counting "
                    "how many components libpostal recovered. Runnable examples are "
                    "carried in this object's example-query metadata.\n\n"
                    "## Notes\n\n"
                    "Values are lower-cased; empty/whitespace input yields no "
                    "rows. See the `address_labels` discovery relation for the full "
                    "label set."
                ),
                keywords=[
                    "parse address",
                    "components",
                    "long format",
                    "label value",
                    "unpivot",
                    "libpostal",
                    "table function",
                    "road",
                    "city",
                    "state",
                    "postcode",
                ],
                relative_path=_TABLES_SRC,
            ),
            # VGI307/VGI321: structured result schema (replaces retired result_columns_md).
            "vgi.result_columns_schema": json.dumps(
                [
                    {
                        "name": "label",
                        "type": "VARCHAR",
                        "description": (
                            "libpostal component label (road, city, state, postcode, country, house_number, unit, ...)."
                        ),
                    },
                    {
                        "name": "value",
                        "type": "VARCHAR",
                        "description": "The (lower-cased) component value.",
                    },
                ]
            ),
            "vgi.executable_examples": _EXECUTABLE_EXAMPLES,
        }
        examples = [
            FunctionExample(
                sql=(
                    "SELECT label, value FROM postal.main.parse_address_components("
                    "'781 Franklin Ave, Brooklyn, NY 11216') ORDER BY label"
                ),
                description="Long-format parse of a US address, one component per row",
            ),
            FunctionExample(
                sql=(
                    "SELECT value FROM postal.main.parse_address_components("
                    "'1600 Pennsylvania Ave NW, Washington, DC 20500') WHERE label = 'city'"
                ),
                description="Pull one component out by label",
            ),
        ]

    @classmethod
    def cardinality(cls, params: BindParams[_ParseComponentsArgs]) -> TableCardinality:
        """Estimate the row count (one row per parsed component)."""
        return TableCardinality(estimate=8, max=len(addresses.COMPONENT_LABELS))

    @classmethod
    def process(cls, params: ProcessParams[_ParseComponentsArgs], state: None, out: OutputCollector) -> None:
        """Emit one ``(label, value)`` row per parsed libpostal component."""
        pairs = addresses.parse_address_pairs(params.args.text)
        out.emit(
            pa.RecordBatch.from_pydict(
                {
                    "label": [label for (label, _value) in pairs],
                    "value": [value for (_label, value) in pairs],
                },
                schema=params.output_schema,
            )
        )
        out.finish()


@dataclass(kw_only=True)
class _NoArgs:
    """``address_labels()`` takes no arguments."""


_ADDRESS_LABELS_SCHEMA = pa.schema(
    [field("label", pa.string(), "A component label libpostal can emit.", nullable=False)]
)


@init_single_worker
@bind_fixed_schema
class AddressLabelsFunction(TableFunctionGenerator[_NoArgs]):
    """Every component label libpostal's parser can emit, one per row.

    Use this to discover the keys you can read out of ``parse_address(...)`` or
    filter on in ``parse_address_components(...)``.
    """

    FIXED_SCHEMA: ClassVar[pa.Schema] = _ADDRESS_LABELS_SCHEMA

    class Meta:
        """Function metadata."""

        name = "address_labels"
        description = "Every component label libpostal's parser can emit (road, city, postcode, ...)"
        categories = ["libpostal", "discovery"]
        tags = {
            **object_tags(
                title="List Address Component Labels",
                category="discovery",
                doc_llm=(
                    "## address_labels\n\n"
                    "Discovery table function: emit **every component label "
                    "libpostal's parser can produce**, one per row (no "
                    "arguments).\n\n"
                    "**Use it when** you need to know which keys you can read out "
                    "of `parse_address(...)` or filter on in "
                    "`parse_address_components(...)` -- e.g. to build a UI, "
                    "validate a label, or pivot components into columns.\n\n"
                    "**Arguments:** none. **Returns:** rows of `(label VARCHAR)`. "
                    "The set is fixed (libpostal's label vocabulary) and "
                    "deterministic."
                ),
                doc_md=(
                    "# address_labels\n\n"
                    "List every component label libpostal can emit -- the "
                    "vocabulary of keys for `parse_address` / "
                    "`parse_address_components`.\n\n"
                    "## Result\n\n"
                    "A single `label` column, one row per component label in "
                    "libpostal's fixed vocabulary (`house_number`, `road`, `city`, "
                    "`state`, `postcode`, `country`, `unit`, and the rest). The set "
                    "is deterministic and takes no arguments, so it doubles as a "
                    "lookup for validating a label or building a picker. Runnable "
                    "examples live in this object's example-query metadata.\n\n"
                    "## Notes\n\n"
                    "Takes no arguments; the returned label set is fixed and "
                    "deterministic."
                ),
                keywords=[
                    "labels",
                    "component labels",
                    "discovery",
                    "schema",
                    "vocabulary",
                    "fields",
                    "keys",
                    "libpostal",
                    "table function",
                    "metadata",
                ],
                relative_path=_TABLES_SRC,
            ),
            # VGI307/VGI321: structured result schema (replaces retired result_columns_md).
            "vgi.result_columns_schema": json.dumps(
                [
                    {
                        "name": "label",
                        "type": "VARCHAR",
                        "description": (
                            "A component label libpostal can emit (road, city, "
                            "state, postcode, country, house_number, unit, ...)."
                        ),
                    }
                ]
            ),
        }
        examples = [
            FunctionExample(
                sql="SELECT count(*) AS label_count FROM postal.main.address_labels()",
                description="How many component labels libpostal emits",
            ),
            FunctionExample(
                sql="SELECT label FROM postal.main.address_labels() ORDER BY label",
                description="List the component labels",
            ),
        ]

    @classmethod
    def cardinality(cls, params: BindParams[_NoArgs]) -> TableCardinality:
        """Return the exact row count (one per component label)."""
        n = len(addresses.COMPONENT_LABELS)
        return TableCardinality(estimate=n, max=n)

    @classmethod
    def process(cls, params: ProcessParams[_NoArgs], state: None, out: OutputCollector) -> None:
        """Emit one row per component label libpostal can emit."""
        out.emit(
            pa.RecordBatch.from_pydict(
                {"label": list(addresses.COMPONENT_LABELS)},
                schema=params.output_schema,
            )
        )
        out.finish()


TABLE_FUNCTIONS: list[type] = [
    ParseAddressComponentsFunction,
    AddressLabelsFunction,
]
