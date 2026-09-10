# splitguard

Deterministic overlap checks for LLM training and evaluation datasets.

When a training, validation, or benchmark split is assembled from several
sources, a copied or lightly edited example can quietly cross the boundary.
`splitguard` checks two local JSON/JSONL files for exact, case-normalized, and
near text overlap, then reports the source lines that need review. It is a
small CI-friendly CLI and Python library: no model, API key, account, network,
database, or cloud service is involved.

## Problem

Evaluation leakage makes scores harder to interpret, while duplicate training
examples waste curation and can distort experiments. Large decontamination
pipelines are useful for corpus-scale work, but a repository often needs a
fast pre-commit check over two files. A generic `sha256` script also misses
case/whitespace changes, chat roles, and near duplicates—and usually loses the
line-level evidence a reviewer needs.

## Quick start

Install from a checkout (Python 3.10+):

```console
git clone https://github.com/thisbejim/splitguard.git
cd splitguard
python3 -m venv .venv
.venv/bin/python -m pip install .
```

Check the included conversation fixtures:

```console
.venv/bin/splitguard examples/train.jsonl examples/eval.jsonl --show-ids
```

```text
splitguard: FAIL
left: left (3 valid, 0 invalid, jsonl; sha256=…)
right: right (3 valid, 0 invalid, jsonl; sha256=…)
overlaps: 1 exact, 0 normalized, 0 near
findings:
  SG001 exact cross: left line 1 (record 1 id='train-001') ↔ right line 1 (record 1 id='eval-001') similarity=1.000 shared_shingles=38
summary: 1 overlap(s), 0 error(s), 0 warning(s)
```

The command exits `1` when an overlap or input error is found, and `0` when
the inputs are clean. `2` means invalid arguments or an unreadable input.

## Useful commands

```console
# Read one side from stdin; reports contain locations and hashes, not text.
cat eval.jsonl | .venv/bin/splitguard train.jsonl - --format json

# Use an explicit field in a custom wrapper (repeat --field for multiple fields).
.venv/bin/splitguard train.jsonl eval.jsonl --field payload.messages

# Include duplicates within each file as well as cross-split overlap.
.venv/bin/splitguard train.jsonl eval.jsonl --within

# Tune near matching for shorter records or a stricter review threshold.
.venv/bin/splitguard train.jsonl eval.jsonl \
  --min-tokens 10 --shingle-size 4 --threshold 0.80

# See a near-overlap finding on the included long-text fixture.
.venv/bin/splitguard examples/near-left.jsonl examples/near-right.jsonl \
  --min-tokens 10 --shingle-size 4 --threshold 0.80

# Emit a stable report for a pipeline or GitHub code-scanning upload.
.venv/bin/splitguard train.jsonl eval.jsonl --format json > overlap.json
.venv/bin/splitguard train.jsonl eval.jsonl --format sarif --strict > overlap.sarif
```

## What it finds

| Code | Finding | Meaning |
| --- | --- | --- |
| `SG001` | Exact overlap | Same canonical text after Unicode NFKC and whitespace normalization |
| `SG002` | Normalized overlap | Same canonical text after case-folding as well |
| `SG003` | Near overlap | Word-shingle Jaccard similarity meets the configured threshold |
| `SG100` | Parse error | Invalid UTF-8, JSON, or JSONL record |
| `SG101` | Record shape | A record is not a JSON object |
| `SG102` | No text | No recognized content; select a field explicitly or review the record |

Short records are not near-matched by default (`--min-tokens 20`), because a
few common words produce noisy similarity. Exact and normalized checks still
run for every record. Matching is deterministic: ties are ordered by finding
kind, similarity, shared shingles, and source line.

## Supported inputs

* JSONL/NDJSON with one JSON object per line.
* A JSON array or one JSON object.
* OpenAI-style `messages` arrays, including text and tool-call content parts.
* ShareGPT-style `conversations` arrays with `from`/`value` turns.
* Other turn arrays such as `turns` and `dialogue`.
* Common scalar fields: `prompt`, `instruction`, `question`, `input`, `query`,
  `completion`, `output`, `response`, `answer`, `target`, `text`, and `content`.
* Explicit dotted paths or JSON Pointers (`/payload/messages`) with
  repeatable `--field`.

Input records are parsed as data only. Tool-call arguments and content parts
are rendered into a canonical comparison string; they are never imported,
evaluated, or executed.

## Reports and privacy

Text is the default report. `--format json` has a versioned schema with input
digests, counts, locations, finding fingerprints, and diagnostics. Markdown is
convenient for a review comment. SARIF uses `SG001`–`SG003` rules with a left
artifact location and a related right location.

Reports do not include prompt, completion, tool-argument, or other record text.
Record IDs are omitted unless `--show-ids` is supplied. File paths and hashes
can still be sensitive, so review reports before sharing them. The tool has no
telemetry and makes no network requests; it never modifies the input files.

## CI

Fail a job when any cross-split overlap is found:

```yaml
- name: Check evaluation leakage
  run: |
    python -m pip install splitguard
    splitguard data/train.jsonl data/eval.jsonl --format sarif --strict > splitguard.sarif
- name: Upload overlap report
  if: always()
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: splitguard.sarif
```

`--strict` also fails on warnings such as a record with no recognizable text.
Use the JSON schema as a stable input to an evaluation orchestrator.

## Why this exists

[EleutherAI's decontamination guide](https://github.com/EleutherAI/lm-evaluation-harness/blob/main/docs/decontamination.md)
and [Open-Instruct's corpus scripts](https://github.com/allenai/open-instruct/tree/main/decontamination)
show the value of n-gram overlap checks, but their indexed workflows are aimed
at large training corpora. The [Hugging Face duplication write-up](https://github.com/huggingface/blog/blob/main/dedup.md)
also calls out duplication and benchmark contamination as data-quality
concerns. `splitguard` is the small missing boundary: two user-owned files,
conversation-aware extraction, line-addressable findings, and a no-dependency
exit code that fits a pull request.

It deliberately does not claim to know whether a private model pre-training
corpus contains a benchmark. It reports observable overlap so a human can
remove, relabel, or justify it.

## Python API

```python
from splitguard import CheckOptions, check

result = check(
    "data/train.jsonl",
    "data/eval.jsonl",
    options=CheckOptions(threshold=0.9, within=True),
)

for finding in result.matches:
    print(finding.kind, finding.left.line, finding.right.line)
```

`CheckResult.to_dict()` returns the same content-free structure used by the
JSON report. `load_dataset()` is available when an application needs to build
its own report or inspect the deterministic hashes.

## Scope and limits

`splitguard` is not a model evaluator, embedding search engine, semantic
similarity oracle, corpus-scale index, data cleaner, or provider client. Near
matching uses configurable word shingles rather than an LLM or embeddings; a
clean result is evidence about the files checked, not proof that a model has
never seen equivalent information elsewhere.

## Development

```console
uv venv --python python3 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
```

The test suite uses synthetic local fixtures only. CI runs the same checks on
Python 3.10–3.14 and needs no API key, model, GPU, or network service.

See [docs/product-spec.md](docs/product-spec.md) for the evidence review,
candidate scorecard, alternatives, and skeptical review.
See [docs/report-schema.md](docs/report-schema.md) for the versioned JSON/SARIF
contract.

## License

MIT. See [LICENSE](LICENSE).
