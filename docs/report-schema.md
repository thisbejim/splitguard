# Report schema

`splitguard --format json` emits schema version `1`. The top-level object has:

* `status`: `PASS`, `WARN`, or `FAIL` (the CLI applies `--strict` when choosing
  this value);
* `options`: the complete matching configuration;
* `datasets.left` and `datasets.right`: path, detected format, byte count,
  record counts, and SHA-256 of each input;
* `counts`: exact, normalized, near, error, warning, and total-match counts;
* `matches`: line-addressable findings with stable rule IDs and fingerprints;
* `diagnostics`: parse and record-shape findings.

The report intentionally contains no record text. Match locations omit IDs by
default; pass `--show-ids` when IDs are safe to include. Hashes are useful for
provenance but can still be sensitive for small or guessable records.

Rule IDs are stable within schema version 1:

| Rule | Meaning |
| --- | --- |
| `SG001` | Exact canonical overlap |
| `SG002` | Case-normalized overlap |
| `SG003` | Near overlap above the configured shingle threshold |
| `SG100` | Input decoding or JSON/JSONL parse error |
| `SG101` | Record is not a JSON object |
| `SG102` | No recognizable content field |

SARIF reports use the same rule IDs and attach the left record as the primary
location and the right record as a related location.
