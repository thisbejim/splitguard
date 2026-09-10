# Product specification: splitguard

Status: implemented in v0.1.0

## Target developer

Evaluation engineers, research engineers, and data-infrastructure engineers who
maintain instruction-tuning, preference, or benchmark datasets as JSONL. The
initial target is a team preparing a training/evaluation split or publishing a
benchmark and wanting a cheap, reviewable overlap check in CI.

## Problem

When a training, validation, or benchmark split is assembled from several
sources, records can be copied, re-wrapped, or lightly edited into another
split. A score can then measure memorization or leakage rather than
generalization. The practical job is:

> When I change a local LLM dataset or eval fixture, I need to know whether
> records overlap across the splits, so that I can remove or review leakage
> before spending GPU time or publishing a misleading result.

The common workaround is a notebook, a one-off hash script, or a large
decontamination pipeline. Those approaches often lose source line numbers,
ignore conversation structure, or require a corpus index and substantial
infrastructure.

## Public evidence

The need is demonstrated by independent projects and public documentation:

* [EleutherAI's lm-evaluation-harness decontamination guide](https://github.com/EleutherAI/lm-evaluation-harness/blob/main/docs/decontamination.md)
  describes leakage as a threat to evaluation validity and builds n-gram
  dictionaries to compare evaluation documents with training data. Its full
  Pile workflow takes days of processing and external storage, which is not a
  convenient pre-commit check for a small local split.
* The [Hugging Face duplication write-up](https://github.com/huggingface/blog/blob/main/dedup.md)
  explains that duplication affects data quality and can cause benchmark
  contamination, while positioning large-scale near-deduplication as a
  specialized workflow.
* [Open-Instruct's decontamination scripts](https://github.com/allenai/open-instruct/tree/main/decontamination)
  require searchable indexes over training datasets and produce separate
  reports for each training/evaluation pair.
* [Meta's benchmark-contamination research](https://ai.meta.com/research/publications/detecting-benchmark-detection-through-watermarking/)
  calls contamination a challenge to the reliability of LLM evaluations.
  This is directly relevant to teams evaluating Llama-family and other
  frontier or open-weight models.
* The [OpenAI fine-tuning format guidance](https://help.openai.com/en/articles/6811186)
  makes message-shaped JSONL a normal artifact in model-development
  workflows; those records are not just generic documents and need a
  conversation-aware comparison.
* A recent [Marin datakit issue](https://github.com/marin-community/marin/issues/6852)
  documents a real decontamination recall trade-off for short or line-broken
  text. splitguard therefore reports exactly what it can prove (exact and
  configurable shingle overlap) rather than claiming to detect all semantic
  contamination.

## Existing workflow and alternatives

| Alternative | What it does well | Gap for this job |
| --- | --- | --- |
| [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness) decontamination | Established n-gram method and benchmark integration | Built around evaluation runs and large indexed corpora; not a small, provider-neutral split gate with source locations |
| [open-instruct decontamination](https://github.com/allenai/open-instruct/tree/main/decontamination) | Practical corpus-scale filtering for training mixtures | Requires indexes, scripts, and a corpus workflow; awkward for a two-file review in CI |
| [text-dedup](https://github.com/ChenghaoMou/text-dedup) | Broad scalable deduplication algorithms | General document processing; does not understand chat roles or emit a minimal cross-split SARIF report |
| [datacrux](https://github.com/stef41/datacrux) | Broad CPU dataset quality toolkit | Bundles many operations and optional dependencies; its contamination check is not the narrow, auditable gate targeted here |
| [llmsanitize](https://github.com/ntunlp/llmsanitize) | Research methods for model/data contamination | Research-oriented, including methods that need a model or larger setup; not a deterministic two-file CI contract |

`splitguard` is justified because it focuses on the smallest useful boundary:
two user-owned files, structured conversation extraction, line-addressable
findings, deterministic hashes, and no model or external index. It complements
rather than replaces corpus-scale research tooling.

## Candidate scorecard

Scores are 0–10 and reflect the hard quality gate in `ai.md`.

| Candidate | Pain | Frequency | Evidence | Frontier relevance | Improvement | Standalone | Maintainability | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Cross-split overlap gate (`splitguard`) | 9 | 8 | 9 | 9 | 8 | 10 | 9 | Build |
| Local GenAI trace redactor | 9 | 8 | 9 | 9 | 7 | 9 | 7 | Reject: existing Langfuse masking and a capable `genai-telemetry-redactor` already cover the core shape |
| Streaming fault-injection server | 8 | 7 | 9 | 9 | 7 | 8 | 7 | Reject: `llmock` and `pi-mock` already provide broad deterministic fault injection |
| Generic evaluation-run diff | 8 | 8 | 8 | 8 | 6 | 9 | 7 | Reject: mature evaluation frameworks already provide run comparison; differentiation would be weak |

The selected candidate clears the gate: problem value 8+, evidence 8+,
expected usefulness 8+, improvement 8+, standalone feasibility 7+, and
maintainability 7+.

## Product thesis

For evaluation and data engineers, `splitguard` checks two structured LLM
dataset splits for exact, normalized, and near text overlap better than a
one-off hash script or corpus pipeline because it is a dependency-free,
conversation-aware CLI that reports deterministic source lines and CI-ready
SARIF without uploading the data.

## Core workflow

```text
training.jsonl + eval.jsonl
            ↓
splitguard (canonicalize common chat shapes, hash, shingle-index, compare)
            ↓
line-addressable text/JSON/Markdown/SARIF findings and exit code
```

## Interface

The primary interface is a CLI that composes with shell pipelines and CI:

```console
splitguard train.jsonl eval.jsonl
cat eval.jsonl | splitguard train.jsonl - --format json
splitguard train.jsonl eval.jsonl --format sarif --strict > splitguard.sarif
```

The Python API exposes the same deterministic contract through `check`,
`load_dataset`, `CheckOptions`, and immutable result dataclasses.

## Supported inputs

* JSONL/NDJSON with one object per line.
* JSON arrays or a single JSON object.
* Common OpenAI-style `messages` and Responses-like content parts.
* ShareGPT-style `conversations` (`from`/`value`) and similar turn arrays.
* Scalar fields such as `prompt`, `instruction`, `question`, `input`,
  `completion`, `output`, `response`, and `answer`.
* Explicit dotted paths or JSON Pointers via repeatable `--field`.

Text is normalized with Unicode NFKC and whitespace folding. The default
near-match mode case-folds text and uses word shingles; threshold, shingle
size, minimum record length, and minimum shared shingles are explicit options.

## Non-goals and honest limits

* It does not claim to determine whether a model's private pre-training corpus
  contains a benchmark.
* It does not perform semantic embedding search or call an LLM.
* It does not upload, rewrite, or delete input files.
* It does not infer whether an overlap is intentional; the human owner reviews
  the line-addressable finding.
* It does not replace corpus-scale filtering or a task-specific evaluator.

Short records are not near-matched by default because a few common words make
similarity unreliable. Exact and normalized matches remain visible regardless
of length.

## Offline and privacy story

All commands operate on local files or stdin. There is no account, network
request, telemetry, model, database, or proprietary API. Reports contain
locations, hashes, and similarity statistics, not record text. Record IDs are
omitted unless `--show-ids` is requested; users should still review paths and
IDs before sharing a report. Inputs are parsed as data and never executed.

## Integration story

The tool is provider-neutral. A dataset prepared for OpenAI fine-tuning,
OpenAI-compatible local servers, Meta/Llama training, or another provider can
be checked without that provider being installed or reachable. Optional
workflow integrations are ordinary shell/CI usage: `--format sarif` can feed
GitHub code scanning, while JSON output can be consumed by an evaluation
orchestrator.

## Final pre-build challenge

An engineer would clone this when a benchmark or fine-tuning PR needs a quick
answer to “did this new split accidentally reuse a training example?” and the
existing corpus tool is too heavy for the repository. It is not a shallow AI
demo because the implementation is deterministic, content-free in reports,
conversation-aware, fixture-tested, and explicit about the boundary between
detectable overlap and unknowable model-training contamination.

## Skeptical review

* **Why might nobody use it?** Teams with tiny, hand-curated datasets may
  inspect them manually. The value increases with generated, merged, or
  frequently revised fixtures; the CLI remains cheap enough to keep in CI.
* **Does an existing tool already solve it?** Corpus-scale tools solve related
  problems, but they require indexes or a framework. `splitguard` targets the
  two-file local gate and preserves source locations and chat roles.
* **Did research mistake complaints for demand?** The evidence includes active
  decontamination implementations, documented large-scale workflows, and
  independent research on evaluation validity—not only feature requests.
* **Is the workflow too niche?** It applies to training, validation, benchmark,
  preference, and agent-fixture splits wherever JSONL records are exchanged.
* **Is the improvement large enough to justify switching?** For a CI check,
  zero runtime dependencies, one command, stable exit codes, and SARIF are a
  meaningful reduction from a notebook or corpus setup. It is intentionally
  complementary rather than a replacement for large-scale pipelines.
* **Will provider changes make it obsolete?** The input contract is generic
  JSON plus documented common message shapes; no undocumented provider API is
  required.
* **Is this infrastructure or an attractive demo?** It has no UI, no model,
  no hosted service, deterministic algorithms, reproducible reports, and tests
  for malformed and adversarial input. The useful output is a CI decision.

The project still passes the quality bar for its chosen scope.
