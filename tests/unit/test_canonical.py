import pytest

from rp.canonical import CanonicalError, canonical_json, digest, is_digest, sha256_digest


def test_rfc8785_key_ordering_uses_utf16_code_units():
    # RFC 8785 §3.2.3: U+1F600 (surrogates D83D DE00) sorts before U+FB33.
    value = {
        "€": "Euro Sign",
        "\r": "Carriage Return",
        "דּ": "Hebrew Letter Dalet With Dagesh",
        "1": "One",
        "\U0001f600": "Emoji: Grinning Face",
        "\u0080": "Control",
        "ö": "Latin Small Letter O With Diaeresis",
    }
    expected = (
        '{"\\r":"Carriage Return","1":"One","\u0080":"Control",'
        '"ö":"Latin Small Letter O With Diaeresis","€":"Euro Sign",'
        '"\U0001f600":"Emoji: Grinning Face","דּ":"Hebrew Letter Dalet With Dagesh"}'
    )
    assert canonical_json(value) == expected.encode("utf-8")


def test_rfc8785_string_escaping():
    # RFC 8785 §3.2.2.2 string example.
    backslash, quote = chr(0x5C), chr(0x22)
    value = chr(0x20AC) + "$" + chr(0x0F) + chr(0x0A) + "A'" + chr(0x42) + quote + backslash * 2 + quote + "/"
    expected = (
        quote + chr(0x20AC) + "$" + backslash + "u000f" + backslash + "n" + "A'B"
        + backslash + quote + backslash * 4 + backslash + quote + "/" + quote
    )
    assert canonical_json(value) == expected.encode("utf-8")


def test_nested_structures_and_literals():
    value = {"b": [1, True, None, {"z": "x", "a": -5}], "a": False}
    assert canonical_json(value) == b'{"a":false,"b":[1,true,null,{"a":-5,"z":"x"}]}'


def test_unicode_is_not_normalised():
    composed = "é"
    decomposed = "é"
    assert canonical_json(composed) != canonical_json(decomposed)


@pytest.mark.parametrize(
    "bad",
    [1.5, float("nan"), float("inf"), 2**53, -(2**53), {1: "x"}, "\ud800", b"bytes", {"k": object()}],
)
def test_rejects_values_outside_the_subset(bad):
    with pytest.raises(CanonicalError):
        canonical_json(bad)


def test_max_safe_integer_is_allowed():
    assert canonical_json(2**53 - 1) == b"9007199254740991"


def test_digest_format():
    d = digest({"a": 1})
    assert is_digest(d)
    assert d == sha256_digest(b'{"a":1}')
    assert not is_digest("sha256:XYZ")
    assert not is_digest("md5:" + "0" * 64)
