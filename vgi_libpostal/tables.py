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
from .schema_utils import field


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
            "vgi.columns_md": (
                "| column | type | description |\n"
                "|---|---|---|\n"
                "| `label` | VARCHAR | libpostal component label (`road`, `city`, "
                "`state`, `postcode`, `country`, `house_number`, `unit`, ...). |\n"
                "| `value` | VARCHAR | The (lower-cased) component value. |"
            ),
        }
        examples = [
            FunctionExample(
                sql="SELECT * FROM postal.parse_address_components('781 Franklin Ave, Brooklyn, NY 11216')",
                description="Long-format parse of a US address",
            ),
            FunctionExample(
                sql=(
                    "SELECT value FROM postal.parse_address_components("
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
            "vgi.columns_md": (
                "| column | type | description |\n"
                "|---|---|---|\n"
                "| `label` | VARCHAR | A component label libpostal can emit "
                "(`road`, `city`, `state`, `postcode`, `country`, `house_number`, "
                "`unit`, ...). |"
            ),
        }
        examples = [
            FunctionExample(
                sql="SELECT count(*) FROM postal.address_labels()",
                description="How many component labels libpostal emits",
            ),
            FunctionExample(
                sql="SELECT label FROM postal.address_labels() ORDER BY label",
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
