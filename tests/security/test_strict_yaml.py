import random

import pytest

from rp import strict_yaml
from rp.strict_yaml import StrictYamlError


def code_of(text, **kwargs):
    with pytest.raises(StrictYamlError) as info:
        strict_yaml.load(text, **kwargs)
    return info.value.code


def test_basic_document():
    data = strict_yaml.load(
        "title: A title\ncount: 12\nflag: true\nnothing: null\nempty:\n"
        "date: 2026-10-10\nversion: '5.2'\nitems:\n  - a\n  - b\n"
    )
    assert data == {
        "title": "A title",
        "count": 12,
        "flag": True,
        "nothing": None,
        "empty": None,
        "date": "2026-10-10",
        "version": "5.2",
        "items": ["a", "b"],
    }


@pytest.mark.parametrize(
    "text, code",
    [
        ("a: 1\na: 2\n", "yaml.duplicate_key"),
        ("country: NO\n", "yaml.ambiguous_scalar"),
        ("answer: yes\n", "yaml.ambiguous_scalar"),
        ("answer: Off\n", "yaml.ambiguous_scalar"),
        ("answer: y\n", "yaml.ambiguous_scalar"),
        ("flag: True\n", "yaml.ambiguous_scalar"),
        ("value: ~\n", "yaml.ambiguous_scalar"),
        ("value: NULL\n", "yaml.ambiguous_scalar"),
        ("version: 5.2\n", "yaml.ambiguous_scalar"),
        ("version: 5.10\n", "yaml.ambiguous_scalar"),
        ("n: 1e3\n", "yaml.ambiguous_scalar"),
        ("n: 007\n", "yaml.ambiguous_scalar"),
        ("n: 0o17\n", "yaml.ambiguous_scalar"),
        ("n: 0x1F\n", "yaml.ambiguous_scalar"),
        ("n: 0b101\n", "yaml.ambiguous_scalar"),
        ("n: +5\n", "yaml.ambiguous_scalar"),
        ("n: 1_000\n", "yaml.ambiguous_scalar"),
        ("n: 1:20\n", "yaml.ambiguous_scalar"),
        ("n: .inf\n", "yaml.ambiguous_scalar"),
        ("n: .NaN\n", "yaml.ambiguous_scalar"),
        ("n: 9007199254740993\n", "yaml.ambiguous_scalar"),
        ("n: =\n", "yaml.ambiguous_scalar"),
        ("a: !!str 1\n", "yaml.tag"),
        ("a: !!python/object:os.system x\n", "yaml.tag"),
        ("a: !custom x\n", "yaml.tag"),
        ("a: &x 1\nb: *x\n", "yaml.anchor"),
        ("base: &b {k: 1}\nother:\n  <<: *b\n", "yaml.anchor"),
        ("other:\n  <<: {k: 1}\n", "yaml.merge_key"),
        ("1: one\n", "yaml.non_string_key"),
        ("true: yes\n", "yaml.non_string_key"),
        ("? [a, b]\n: c\n", "yaml.non_string_key"),
        ("a: 1\n---\nb: 2\n", "yaml.multiple_documents"),
        ("", "yaml.empty"),
        ("# only a comment\n", "yaml.empty"),
        ("a: [1, 2\n", "yaml.syntax"),
        ("a:\n\tb: 1\n", "yaml.syntax"),
    ],
)
def test_rejections(text, code):
    assert code_of(text) == code


def test_billion_laughs_is_rejected_before_expansion():
    text = 'a: &a ["lol","lol"]\nb: &b [*a,*a]\nc: &c [*b,*b]\n'
    assert code_of(text) == "yaml.anchor"


def test_depth_limit():
    text = "a: " + "[" * 40 + "]" * 40 + "\n"
    assert code_of(text) == "yaml.too_deep"


def test_size_limit():
    assert code_of(b"a: " + b"x" * 100, max_bytes=50) == "yaml.too_large"


def test_invalid_utf8():
    assert code_of(b"a: \xff\xfe\n") == "yaml.encoding"


def test_utf8_bom_is_accepted():
    assert strict_yaml.load("\ufeffa: b\n".encode("utf-8")) == {"a": "b"}


def test_error_carries_location():
    with pytest.raises(StrictYamlError) as info:
        strict_yaml.load("first: ok\nsecond: yes\n")
    assert info.value.line == 2


TRICKY_STRINGS = [
    "yes", "No", "on", "OFF", "y", "N", "true", "False", "null", "Null", "~", "",
    "5.2", "5.10", "1e3", "007", "0o17", "0x1F", "+5", "-0", "1_000", "1:20", ".inf", ".nan",
    "2026-10-10", "2026-10-10T12:00:00Z", "<<", "=", "- item", "key: value", "#comment",
    " leading", "trailing ", "multi\nline\n", "multi\nline no trailing", "\nleading newline",
    "quote ' and \" both", "tab\there", "unicode é ∑ 🙂", "@at", "`tick", "!bang", "&amp", "*star",
    "%percent", "[list]", "{map}", "a,b", "?q", "|pipe", ">gt", "9007199254740993",
]


@pytest.mark.parametrize("text", TRICKY_STRINGS)
def test_dump_round_trips_tricky_strings(text):
    data = {"value": text, "list": [text], text if text else "k": 1}
    assert strict_yaml.load(strict_yaml.dump(data)) == data


def test_dump_round_trips_random_documents():
    rng = random.Random(20261011)
    alphabet = "ab yesnoNO01.:-_#'\"\n\t é🙂"

    def rand_value(depth):
        kind = rng.randrange(6 if depth < 4 else 4)
        if kind == 0:
            return "".join(rng.choice(alphabet) for _ in range(rng.randrange(8)))
        if kind == 1:
            return rng.randrange(-(10**6), 10**6)
        if kind == 2:
            return rng.choice([True, False, None])
        if kind == 3:
            return rng.choice(TRICKY_STRINGS)
        if kind == 4:
            return [rand_value(depth + 1) for _ in range(rng.randrange(4))]
        return {f"k{i}{rng.choice(TRICKY_STRINGS)}": rand_value(depth + 1) for i in range(rng.randrange(4))}

    for _ in range(300):
        data = {"root": rand_value(0)}
        assert strict_yaml.load(strict_yaml.dump(data)) == data


def test_dump_rejects_floats():
    with pytest.raises(StrictYamlError):
        strict_yaml.dump({"x": 0.5})


def test_dump_never_emits_anchors_for_shared_objects():
    shared = {"k": "v"}
    text = strict_yaml.dump({"a": shared, "b": shared})
    assert "&" not in text and "*" not in text
    assert strict_yaml.load(text) == {"a": shared, "b": shared}
