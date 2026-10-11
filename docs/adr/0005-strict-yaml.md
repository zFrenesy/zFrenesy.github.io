# ADR 0005: Strict YAML profile for authored metadata

Status: Accepted, 2026-10-11 (milestone 1 plan)

## Context

§4 requires authoring YAML to be safely parsed, rejecting duplicate keys, ambiguous scalar coercions, unsafe tags and unknown core fields. PyYAML follows YAML 1.1, where `NO`, `yes`, `on`, `5.10` and `1:20` silently become booleans, floats or integers. Other tools follow YAML 1.2, where `0o17` and `1e3` are numbers.

## Decision

`rp.strict_yaml.load` composes the node graph with PyYAML's safe parser and converts nodes itself, so no YAML constructor runs.

It rejects, each with a stable error code:

- duplicate keys, non-string keys and merge keys;
- explicit tags, anchors and aliases (which also prevents "billion laughs" expansion);
- multiple documents and empty documents;
- input larger than 256 KiB or nested more than 32 levels;
- invalid UTF-8;
- any plain scalar that some YAML reader would coerce: YAML 1.1 booleans in any case, including `y` and `n`; null spellings other than `null`; floats; `.inf` and `.nan`; octal, hex and binary; signed or zero-padded integers; digit separators; sexagesimal numbers; integers beyond 2^53 − 1.

Only `true`, `false`, `null` (or an empty value) and plain decimal integers become non-strings. Everything else, including unquoted dates, is a string, and schemas check its format.

`rp.strict_yaml.dump` writes deterministic YAML in insertion order. It quotes any string the loader would otherwise reject and never emits anchors, so `load(dump(x)) == x`. Round-trip tests cover tricky strings and 300 random documents.

## Consequences

Contributors who edit YAML by hand must quote model versions (`version: "5.2"`) and letter codes such as `"N"`. The loader's error says so and gives the line. Most contributors never write YAML: the intake App writes it (§16.2). The rule caught a real case while building this milestone: the JEL top-level categories `N` and `Y` in the policy files.
