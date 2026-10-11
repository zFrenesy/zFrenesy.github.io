# Economics catalogue presentation

The trusted platform owns the Economics display order and JEL names. Changing
them requires a site rebuild, without editing research records, aliases,
statements, revision histories or URLs.

## Current rank

Edit `site/catalogues/economics-rankings.csv`. Keep each permanent `Problem ID`
exactly once and change `New rank` to the desired order. Use each integer from 1
through the number of entries exactly once. The CSV is compatible with the
legacy catalogue's permanent identifiers; for example, `C73-1` identifies
`ECON-C73-1` regardless of its current rank. Do not use reused `OP-` source IDs
or infer a current rank from the number in an alias.

Validate before rebuilding:

```sh
python -m rp.site.rankings
```

To validate a proposed replacement without changing the active configuration:

```sh
python -m rp.site.rankings --rankings /path/to/proposed-ranks.csv
```

The loader rejects invalid IDs, duplicate IDs, ties, gaps and non-integer ranks.
Title and JEL columns are retained for human review; a provided JEL code must
match the permanent ID. The current title in the research record remains the
displayed title. New problems without a configured rank appear after ranked
problems, in stable alias order, with no invented numeric rank. Add a newly
registered permanent ID to this CSV when the catalogue assigns it a rank.

## Classification names

Edit `site/catalogues/economics-jel.json` to update classification names. The
lookup includes parent categories as well as individual codes, so code and
category-name searches can share the same vocabulary. Future unknown codes
retain their code as the display fallback until a name is added.

## Initial snapshot and provenance

Both initial configuration files were copied byte-for-byte from
`mehmetmars7/Erdosproblems-llm-hunter` commit
`b1f633121074e16579fa7fd05314e5f504d29bae`, using read-only Git object access:

| Platform file | Pinned legacy file | Initial SHA-256 |
| --- | --- | --- |
| `site/catalogues/economics-rankings.csv` | `lists/economics/rankings.csv` | `c0c8d41647c86f01596e62c81504b142cc5d1734c16176b2b32fc3b1f9e0f970` |
| `site/catalogues/economics-jel.json` | `lists/economics/jel_codes.json` | `da7255b6c47c75de3674b48273e8ccf212e6995fd2e764af68f8d6435b6136c6` |

The initial CSV contains 657 entries. Its initial order matches the legacy
catalogue's ascending current rank, beginning `C73-1`, `C72-2`, `D63-3`. These
are catalogue ranks, not a computed assessment of the research attempts.
The JEL lookup retains the legacy file's source note and source-text digest:
user-supplied classification text dated 2026-10-09. These hashes document the
initial import; later deliberate configuration edits are expected to change
the file hashes.
