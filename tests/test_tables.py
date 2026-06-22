"""Integration tests for the libpostal table functions.

Drives ``parse_address_components`` and ``address_labels`` through the real
bind -> init -> process lifecycle in-process (no worker subprocess). libpostal
LOWER-CASES its output; assertions are against lower case.
"""

from __future__ import annotations

import pyarrow as pa

from vgi_libpostal.tables import AddressLabelsFunction, ParseAddressComponentsFunction

from .harness import invoke_table_function


class TestParseAddressComponents:
    def test_long_format_rows(self) -> None:
        table = invoke_table_function(
            ParseAddressComponentsFunction,
            positional=(pa.scalar("781 Franklin Ave, Brooklyn, NY 11216"),),
        )
        assert table.column_names == ["label", "value"]
        mapping = dict(zip(table.column("label").to_pylist(), table.column("value").to_pylist(), strict=True))
        assert mapping["house_number"] == "781"
        assert "franklin ave" in mapping["road"]
        assert mapping["state"] == "ny"
        assert mapping["postcode"] == "11216"

    def test_empty_input_no_rows(self) -> None:
        table = invoke_table_function(ParseAddressComponentsFunction, positional=(pa.scalar(""),))
        assert table.num_rows == 0


class TestAddressLabels:
    def test_columns_and_nonempty(self) -> None:
        table = invoke_table_function(AddressLabelsFunction)
        assert table.column_names == ["label"]
        assert table.num_rows > 0

    def test_core_labels_present(self) -> None:
        table = invoke_table_function(AddressLabelsFunction)
        labels = set(table.column("label").to_pylist())
        for core in ("road", "city", "state", "postcode", "country"):
            assert core in labels
