"""Unit tests for the pure address logic (no Arrow / VGI involved).

These call ``vgi_libpostal.addresses`` directly and exercise real libpostal
behaviour. libpostal LOWER-CASES its output, so every assertion is against
lower case. Vectors are chosen so libpostal's labelling is deterministic.
"""

from __future__ import annotations

from vgi_libpostal import addresses


class TestParseAddressMap:
    def test_known_components(self) -> None:
        m = addresses.parse_address_map("781 Franklin Ave Crown Heights Brooklyn NY 11216")
        # libpostal lower-cases; assert against lower case.
        assert m["house_number"] == "781"
        assert "franklin ave" in m["road"]
        assert m["state"] == "ny"
        assert m["postcode"] == "11216"

    def test_city_and_unit(self) -> None:
        m = addresses.parse_address_map("Apt 5B 120 E 96th St New York NY 10128")
        assert m["city"] == "new york"
        assert m["unit"] == "apt 5b"
        assert m["house_number"] == "120"

    def test_country(self) -> None:
        m = addresses.parse_address_map("10 Downing Street, London SW1A 2AA, United Kingdom")
        assert m["country"] == "united kingdom"
        assert m["city"] == "london"

    def test_empty_string_is_empty_map(self) -> None:
        assert addresses.parse_address_map("") == {}
        assert addresses.parse_address_map("   ") == {}

    def test_none_is_empty_map(self) -> None:
        assert addresses.parse_address_map(None) == {}

    def test_single_token(self) -> None:
        # A lone token still parses to a single component (no crash).
        m = addresses.parse_address_map("Brooklyn")
        assert m  # non-empty
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in m.items())

    def test_unicode(self) -> None:
        m = addresses.parse_address_map("Hauptstraße 5, 80331 München, Deutschland")
        assert m["postcode"] == "80331"
        # Unicode preserved (lower-cased).
        assert "münchen" in " ".join(m.values())


class TestParseAddressPairs:
    def test_order_and_labels(self) -> None:
        pairs = addresses.parse_address_pairs("781 Franklin Ave, Brooklyn, NY 11216")
        labels = [label for label, _ in pairs]
        assert "house_number" in labels
        assert "road" in labels
        assert "postcode" in labels
        # All pairs are (str, str).
        assert all(isinstance(a, str) and isinstance(b, str) for a, b in pairs)

    def test_empty_and_none(self) -> None:
        assert addresses.parse_address_pairs("") == []
        assert addresses.parse_address_pairs(None) == []

    def test_garbage_does_not_raise(self) -> None:
        # Garbage still parses to *something* without raising.
        pairs = addresses.parse_address_pairs("!!! ??? ###")
        assert isinstance(pairs, list)


class TestAddressComponent:
    def test_present(self) -> None:
        addr = "781 Franklin Ave, Brooklyn, NY 11216"
        assert addresses.address_component(addr, "postcode") == "11216"
        assert addresses.address_component(addr, "state") == "ny"
        assert "franklin ave" in addresses.address_component(addr, "road")

    def test_absent_is_none(self) -> None:
        # No country in this US address.
        assert addresses.address_component("781 Franklin Ave, Brooklyn, NY 11216", "country") is None

    def test_none_input(self) -> None:
        assert addresses.address_component(None, "road") is None


class TestExpandAddress:
    def test_expands_abbreviations(self) -> None:
        out = addresses.expand_address("120 E 96th St")
        joined = " || ".join(out)
        # 'E' expands to 'east' and 'St' to 'street' in at least one expansion.
        assert any("east" in e for e in out)
        assert any("street" in e for e in out)
        assert joined  # non-empty

    def test_empty_and_none(self) -> None:
        assert addresses.expand_address("") == []
        assert addresses.expand_address("   ") == []
        assert addresses.expand_address(None) == []

    def test_returns_lowercase_strings(self) -> None:
        out = addresses.expand_address("120 E 96th St")
        assert all(e == e.lower() for e in out)


class TestComponentLabels:
    def test_nonempty_and_includes_core(self) -> None:
        for core in ("road", "city", "state", "postcode", "country", "house_number", "unit"):
            assert core in addresses.COMPONENT_LABELS

    def test_all_strings(self) -> None:
        assert all(isinstance(x, str) for x in addresses.COMPONENT_LABELS)
