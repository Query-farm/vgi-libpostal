"""Keep the composed example queries in sync with their pinned E2E results.

``vgi_libpostal.meta.COMPOSED_*`` examples are published as metadata; their
output is asserted by ``test/sql/composed.test`` (haybarn-unittest). This guards
that the SQL there is exactly the published SQL, and that each composed example
is reachable from the schema list and from its driving object's first five
examples (the vgi-lint agent simulator only shows per-object examples).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vgi_libpostal import meta
from vgi_libpostal.scalars import ExpandAddressFunction
from vgi_libpostal.tables import _EXECUTABLE_EXAMPLES, AddressLabelsFunction, ParseAddressComponentsFunction
from vgi_libpostal.worker import _DISCOVERY_TABLES, _SCHEMA_EXAMPLE_QUERIES

_COMPOSED_SQL_TEST = Path(__file__).resolve().parent.parent / "test" / "sql" / "composed.test"

_DRIVERS = [
    (meta.COMPOSED_DEDUP_EXAMPLE, ExpandAddressFunction),
    (meta.COMPOSED_NORMALIZE_COMPONENTS_EXAMPLE, ParseAddressComponentsFunction),
    (meta.COMPOSED_LABEL_COVERAGE_EXAMPLE, AddressLabelsFunction),
]


@pytest.mark.parametrize(("example", "driver"), _DRIVERS)
def test_composed_example_is_published_and_pinned(example: dict[str, str], driver: type) -> None:
    assert example["sql"] in _COMPOSED_SQL_TEST.read_text()
    assert example in json.loads(_SCHEMA_EXAMPLE_QUERIES)
    assert example in json.loads(driver.Meta.tags["vgi.example_queries"])[:5]
    assert example in json.loads(_EXECUTABLE_EXAMPLES)


def test_label_coverage_example_on_address_labels_table() -> None:
    (table,) = _DISCOVERY_TABLES
    assert meta.COMPOSED_LABEL_COVERAGE_EXAMPLE in json.loads(table.tags["vgi.example_queries"])[:5]
