"""End-to-end tests for the per-row scalar libpostal functions.

These spawn ``libpostal_worker.py`` as a subprocess via ``vgi.client.Client``
and call each scalar exactly as DuckDB would after ``ATTACH``. The ``text``
column travels in the input batch (a ``Param``). libpostal LOWER-CASES its
output, so assertions are against lower case.

The worker is launched with the current interpreter (``sys.executable``), whose
environment already has the compiled ``postal`` binding -- no rebuild.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa
import pytest
from vgi import Arguments
from vgi.client import Client

_WORKER = str(Path(__file__).resolve().parent.parent / "libpostal_worker.py")


@pytest.fixture(scope="module")
def client() -> Iterator[Client]:
    # Current interpreter (postal already compiled) + worker_limit=1 so output
    # order matches input order for deterministic per-row assertions.
    with Client(f"{sys.executable} {_WORKER}", worker_limit=1) as c:
        yield c


def _scalar(client: Client, name: str, values: list) -> list:
    batch = pa.RecordBatch.from_pydict({"t": pa.array(values, type=pa.string())})
    results = list(
        client.scalar_function(
            function_name=name,
            input=iter([batch]),
            arguments=Arguments(positional=[]),
        )
    )
    return results[0]["result"].to_pylist()


class TestParseAddress:
    def test_returns_map(self, client: Client) -> None:
        out = _scalar(client, "parse_address", ["781 Franklin Ave Crown Heights Brooklyn NY 11216"])
        # MAP comes back as a list of (key, value) tuples; build a dict.
        m = dict(out[0])
        assert "franklin ave" in m["road"]
        assert m["state"] == "ny"
        assert m["postcode"] == "11216"

    def test_city(self, client: Client) -> None:
        out = _scalar(client, "parse_address", ["1600 Pennsylvania Ave NW, Washington, DC 20500"])
        assert dict(out[0])["city"] == "washington"

    def test_empty_string_is_empty_map(self, client: Client) -> None:
        out = _scalar(client, "parse_address", [""])
        assert dict(out[0]) == {}

    def test_null_is_null(self, client: Client) -> None:
        out = _scalar(client, "parse_address", [None])
        assert out[0] is None


class TestExpandAddress:
    def test_expands(self, client: Client) -> None:
        out = _scalar(client, "expand_address", ["120 E 96th St"])
        expansions = out[0]
        assert any("east" in e for e in expansions)
        assert any("street" in e for e in expansions)

    def test_empty_and_null(self, client: Client) -> None:
        assert _scalar(client, "expand_address", [""])[0] == []
        assert _scalar(client, "expand_address", [None])[0] is None


class TestComponentExtractors:
    def test_postcode_road_state(self, client: Client) -> None:
        addr = "781 Franklin Ave, Brooklyn, NY 11216"
        assert _scalar(client, "address_postcode", [addr]) == ["11216"]
        assert _scalar(client, "address_state", [addr]) == ["ny"]
        assert "franklin ave" in _scalar(client, "address_road", [addr])[0]

    def test_house_number_and_city(self, client: Client) -> None:
        addr = "1600 Pennsylvania Ave NW, Washington, DC 20500"
        assert _scalar(client, "address_house_number", [addr]) == ["1600"]
        assert _scalar(client, "address_city", [addr]) == ["washington"]

    def test_unit(self, client: Client) -> None:
        assert _scalar(client, "address_unit", ["Apt 5B, 120 E 96th St, New York, NY 10128"]) == ["apt 5b"]

    def test_country(self, client: Client) -> None:
        assert _scalar(client, "address_country", ["10 Downing St, London SW1A 2AA, United Kingdom"]) == [
            "united kingdom"
        ]

    def test_absent_component_is_null(self, client: Client) -> None:
        # No country in this US address.
        assert _scalar(client, "address_country", ["781 Franklin Ave, Brooklyn, NY 11216"]) == [None]

    def test_null_input_is_null(self, client: Client) -> None:
        assert _scalar(client, "address_postcode", [None]) == [None]
