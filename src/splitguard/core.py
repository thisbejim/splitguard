"""Core data loading and deterministic overlap detection for splitguard."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TextIO

Severity = Literal["error", "warning", "info"]
InputFormat = Literal["auto", "json", "jsonl"]
Normalization = Literal["strict", "text"]

_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_ID_KEYS = ("id", "uid", "uuid", "example_id", "exampleId", "custom_id", "key")
_INPUT_KEYS = ("prompt", "instruction", "question", "input", "user", "query")
_OUTPUT_KEYS = ("completion", "output", "response", "answer", "target", "assistant")
_COMMON_KEYS = (
    "system",
    "context",
    "prompt",
    "instruction",
    "question",
    "input",
    "user",
    "query",
    "completion",
    "output",
    "response",
    "answer",
    "target",
    "assistant",
    "text",
    "content",
)
_META_KEYS = {
    "id",
    "uid",
    "uuid",
    "example_id",
    "exampleid",
    "custom_id",
    "key",
    "metadata",
    "meta",
    "tags",
    "source",
    "split",
    "dataset",
    "license",
    "created_at",
    "updated_at",
}
_ROLE_ALIASES = {
    "human": "user",
    "gpt": "assistant",
    "model": "assistant",
    "bot": "assistant",
    "observation": "tool",
    "function": "tool",
}


@dataclass(frozen=True)
class Diagnostic:
    """A non-overlap issue found while reading a dataset."""

    severity: Severity
    code: str
    dataset: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "dataset": self.dataset,
            "message": self.message,
        }
        if self.line is not None:
            result["line"] = self.line
        return result


@dataclass(frozen=True)
class DatasetSummary:
    """Safe metadata about one input file."""

    label: str
    path: str
    input_format: str
    sha256: str
    bytes: int
    records: int
    invalid_records: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "path": self.path,
            "format": self.input_format,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "records": self.records,
            "invalid_records": self.invalid_records,
        }


@dataclass(frozen=True)
class Location:
    """A report-safe pointer to a dataset record."""

    dataset: str
    line: int
    ordinal: int
    record_id: str | None

    def to_dict(self, *, include_id: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "dataset": self.dataset,
            "line": self.line,
            "record": self.ordinal,
        }
        if include_id and self.record_id is not None:
            result["id"] = self.record_id
        return result


@dataclass(frozen=True)
class Record:
    """Normalized, non-content representation used by the matcher."""

    location: Location
    strict_digest: str
    normalized_digest: str
    token_count: int
    shingles: frozenset[str]


@dataclass(frozen=True)
class Finding:
    """One exact, normalized, or near overlap."""

    kind: Literal["exact", "normalized", "near"]
    scope: Literal["cross", "within"]
    left: Location
    right: Location
    similarity: float
    shared_shingles: int
    left_digest: str
    right_digest: str

    @property
    def rule_id(self) -> str:
        return {"exact": "SG001", "normalized": "SG002", "near": "SG003"}[self.kind]

    def fingerprint(self) -> str:
        value = "|".join(
            (
                self.rule_id,
                self.scope,
                self.left.dataset,
                str(self.left.line),
                self.right.dataset,
                str(self.right.line),
            )
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    def to_dict(self, *, include_ids: bool = False) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "kind": self.kind,
            "scope": self.scope,
            "similarity": round(self.similarity, 6),
            "shared_shingles": self.shared_shingles,
            "left": self.left.to_dict(include_id=include_ids),
            "right": self.right.to_dict(include_id=include_ids),
            "left_sha256": self.left_digest,
            "right_sha256": self.right_digest,
            "fingerprint": self.fingerprint(),
        }


@dataclass(frozen=True)
class CheckOptions:
    """Matching settings recorded in every report."""

    fields: tuple[str, ...] = ()
    shingle_size: int = 5
    threshold: float = 0.85
    min_tokens: int = 20
    min_shared_shingles: int = 3
    max_matches: int = 5
    within: bool = False
    input_format: InputFormat = "auto"
    normalization: Normalization = "text"

    def validate(self) -> None:
        if self.input_format not in {"auto", "json", "jsonl"}:
            raise ValueError("input_format must be auto, json, or jsonl")
        if self.normalization not in {"strict", "text"}:
            raise ValueError("normalization must be strict or text")
        if self.shingle_size < 1:
            raise ValueError("shingle_size must be at least 1")
        if not 0.0 < self.threshold <= 1.0:
            raise ValueError("threshold must be greater than 0 and at most 1")
        if self.min_tokens < 1:
            raise ValueError("min_tokens must be at least 1")
        if self.min_shared_shingles < 1:
            raise ValueError("min_shared_shingles must be at least 1")
        if self.max_matches < 1:
            raise ValueError("max_matches must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "fields": list(self.fields),
            "shingle_size": self.shingle_size,
            "threshold": self.threshold,
            "min_tokens": self.min_tokens,
            "min_shared_shingles": self.min_shared_shingles,
            "max_matches": self.max_matches,
            "within": self.within,
            "input_format": self.input_format,
            "normalization": self.normalization,
        }


@dataclass(frozen=True)
class CheckResult:
    """Complete result returned by the library and CLI."""

    left: DatasetSummary
    right: DatasetSummary
    matches: tuple[Finding, ...]
    diagnostics: tuple[Diagnostic, ...]
    options: CheckOptions

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity == "error")

    @property
    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity == "warning")

    def status(self, *, strict: bool = False) -> Literal["PASS", "WARN", "FAIL"]:
        if self.matches or self.errors or (strict and self.warnings):
            return "FAIL"
        if self.warnings:
            return "WARN"
        return "PASS"

    def counts(self) -> dict[str, int]:
        counts: Counter[str] = Counter(f.kind for f in self.matches)
        counts.update({"errors": len(self.errors), "warnings": len(self.warnings)})
        return {
            "exact": counts.get("exact", 0),
            "normalized": counts.get("normalized", 0),
            "near": counts.get("near", 0),
            "errors": counts.get("errors", 0),
            "warnings": counts.get("warnings", 0),
            "total_matches": len(self.matches),
        }

    def to_dict(self, *, include_ids: bool = False) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": self.status(),
            "options": self.options.to_dict(),
            "datasets": {"left": self.left.to_dict(), "right": self.right.to_dict()},
            "counts": self.counts(),
            "matches": [m.to_dict(include_ids=include_ids) for m in self.matches],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }


@dataclass(frozen=True)
class LoadedDataset:
    records: tuple[Record, ...]
    diagnostics: tuple[Diagnostic, ...]
    summary: DatasetSummary


def _path_parts(path: str) -> tuple[str, ...]:
    if path.startswith("/"):
        return tuple(part.replace("~1", "/").replace("~0", "~") for part in path.split("/")[1:])
    return tuple(part for part in path.split(".") if part)


def _lookup(value: Any, path: str) -> Any:
    current = value
    for part in _path_parts(path):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif (
            isinstance(current, Sequence)
            and not isinstance(current, (str, bytes))
            and part.isdigit()
        ):
            index = int(part)
            if index >= len(current):
                raise KeyError(path)
            current = current[index]
        else:
            raise KeyError(path)
    return current


def _canonical_whitespace(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(value.split())


def normalize_text(value: str, mode: Normalization = "text") -> str:
    """Return stable text used for exact and shingle comparisons."""

    normalized = _canonical_whitespace(value)
    if mode == "text":
        normalized = normalized.casefold()
    return normalized


def _role(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    role = value.strip().casefold() or "unknown"
    return _ROLE_ALIASES.get(role, role)


def _json_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


def _render_value(value: Any) -> str:
    """Render content parts without carrying image URLs or arbitrary metadata."""

    if isinstance(value, str):
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return _json_scalar(value)
    if isinstance(value, list):
        rendered = [_render_value(item) for item in value]
        return " ".join(item for item in rendered if item)
    if isinstance(value, Mapping):
        for key in ("text", "input_text", "output_text", "value"):
            if key in value:
                return _render_value(value[key])
        if "content" in value:
            return _render_value(value["content"])
        if "image_url" in value or value.get("type") in {
            "input_image",
            "image",
            "audio",
            "input_audio",
        }:
            return f"<{value.get('type', 'image')}>"
        if "tool_calls" in value:
            return _render_tool_calls(value["tool_calls"])
        if "name" in value and "arguments" in value:
            return _render_tool_calls([value])
        # Explicit fields may intentionally contain structured JSON. Keep it stable.
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def _render_tool_calls(value: Any) -> str:
    calls = value if isinstance(value, list) else [value]
    rendered: list[str] = []
    for call in calls:
        if not isinstance(call, Mapping):
            rendered.append(_render_value(call))
            continue
        function = call.get("function", call)
        if isinstance(function, Mapping):
            name = _render_value(function.get("name", "unknown"))
            arguments = function.get("arguments", function.get("input", {}))
            if isinstance(arguments, str):
                argument_text = arguments
            else:
                argument_text = json.dumps(
                    arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
            rendered.append(f"tool_call {name} {argument_text}")
        else:
            rendered.append(_render_value(function))
    return " ".join(rendered)


def _render_conversation(value: Any) -> str:
    if not isinstance(value, list):
        return _render_value(value)
    parts: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            role_value = item.get(
                "role", item.get("from", item.get("speaker", item.get("author", "unknown")))
            )
            role = _role(role_value)
            used_tool_content = False
            if "content" in item:
                content = _render_value(item["content"])
            elif "value" in item:
                content = _render_value(item["value"])
            elif "text" in item:
                content = _render_value(item["text"])
            elif "tool_calls" in item:
                content = _render_tool_calls(item["tool_calls"])
                used_tool_content = True
            elif "function_call" in item:
                content = _render_tool_calls([item["function_call"]])
                used_tool_content = True
            else:
                content = _render_value(item)
            if "tool_calls" in item and not used_tool_content:
                tool_text = _render_tool_calls(item["tool_calls"])
                content = f"{content} {tool_text}".strip()
            if "function_call" in item and not used_tool_content:
                tool_text = _render_tool_calls([item["function_call"]])
                content = f"{content} {tool_text}".strip()
            if content:
                parts.append(f"{role}: {content}")
        else:
            content = _render_value(item)
            if content:
                parts.append(f"unknown: {content}")
    return "\n".join(parts)


def _field_alias(name: str) -> str:
    leaf = name.rsplit("/", 1)[-1].rsplit(".", 1)[-1].casefold()
    if leaf in _INPUT_KEYS:
        return "input"
    if leaf in _OUTPUT_KEYS:
        return "output"
    if leaf in {"messages", "conversations", "turns", "dialogue"}:
        return "conversation"
    return leaf or "value"


def _fragments_for_record(
    record: Mapping[str, Any], fields: tuple[str, ...]
) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = []
    if fields:
        for field in fields:
            try:
                value = _lookup(record, field)
            except KeyError:
                continue
            if _field_alias(field) == "conversation":
                rendered = _render_conversation(value)
            else:
                rendered = _render_value(value)
            if rendered.strip():
                fragments.append((_field_alias(field), rendered))
        return fragments

    for key in ("messages", "conversations", "turns", "dialogue"):
        value = record.get(key)
        if isinstance(value, list):
            rendered = _render_conversation(value)
            if rendered.strip():
                return [("conversation", rendered)]

    for key in _COMMON_KEYS:
        if key not in record:
            continue
        rendered = _render_value(record[key])
        if rendered.strip():
            fragments.append((_field_alias(key), rendered))
    if fragments:
        return fragments

    # A one-level wrapper is common in exported evaluation artifacts.
    for wrapper in ("data", "example", "record", "payload"):
        nested = record.get(wrapper)
        if isinstance(nested, Mapping):
            nested_fragments = _fragments_for_record(nested, ())
            if nested_fragments:
                return nested_fragments

    # Last-resort support for simple custom records, while never treating IDs or
    # metadata as model text.
    for key, value in record.items():
        if key.casefold() in _META_KEYS:
            continue
        if isinstance(value, str) and value.strip():
            fragments.append((_field_alias(key), value))
    return fragments


def _record_id(record: Mapping[str, Any]) -> str | None:
    for key in _ID_KEYS:
        value = record.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value)
    return None


def _record_from_value(
    value: Any,
    *,
    dataset: str,
    line: int,
    ordinal: int,
    options: CheckOptions,
) -> tuple[Record | None, Diagnostic | None]:
    if not isinstance(value, Mapping):
        return None, Diagnostic("error", "SG101", dataset, "record must be a JSON object", line)
    fragments = _fragments_for_record(value, options.fields)
    if not fragments:
        return (
            None,
            Diagnostic(
                "warning",
                "SG102",
                dataset,
                "record has no recognizable text; use --field to select its content",
                line,
            ),
        )
    canonical = "\n".join(f"{kind}: {text}" for kind, text in fragments)
    strict = normalize_text(canonical, "strict")
    normalized = normalize_text(canonical, options.normalization)
    tokens = tuple(_TOKEN_RE.findall(normalized))
    shingle_values = (
        " ".join(tokens[index : index + options.shingle_size])
        for index in range(len(tokens) - options.shingle_size + 1)
    )
    shingles = frozenset(shingle_values)
    location = Location(dataset, line, ordinal, _record_id(value))
    return (
        Record(
            location=location,
            strict_digest=hashlib.sha256(strict.encode("utf-8")).hexdigest(),
            normalized_digest=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            token_count=len(tokens),
            shingles=shingles,
        ),
        None,
    )


def _read_source(path: str, stdin: TextIO | None) -> tuple[bytes, str | None]:
    if path == "-":
        text = (stdin or sys.stdin).read()
        return text.encode("utf-8"), None
    source = Path(path)
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise OSError(f"cannot read {path}: {exc}") from exc
    return data, None


def _payloads(
    data: bytes, *, path: str, input_format: InputFormat, extension: str = ""
) -> tuple[list[tuple[int, Any]], str, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        diagnostics.append(
            Diagnostic("error", "SG100", path, f"input is not valid UTF-8 ({exc.start + 1})", None)
        )
        return [], "unknown", diagnostics

    stripped = text.lstrip()
    detected: InputFormat
    if input_format == "auto":
        if extension in {".jsonl", ".ndjson"}:
            detected = "jsonl"
        elif extension == ".json":
            detected = "json"
        else:
            detected = "jsonl"
            # Try one complete JSON value first. A JSONL file with multiple
            # objects raises ``Extra data`` and then falls through to line parsing.
            if stripped.startswith(("[", "{")):
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(value, list):
                        return (
                            [(index + 1, item) for index, item in enumerate(value)],
                            "json",
                            diagnostics,
                        )
                    return [(1, value)], "json", diagnostics
    else:
        detected = input_format

    if detected == "json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            diagnostics.append(
                Diagnostic("error", "SG100", path, f"invalid JSON: {exc.msg}", exc.lineno)
            )
            return [], "json", diagnostics
        if isinstance(value, list):
            return [(index + 1, item) for index, item in enumerate(value)], "json", diagnostics
        return [(1, value)], "json", diagnostics

    payloads: list[tuple[int, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payloads.append((line_number, json.loads(line)))
        except json.JSONDecodeError as exc:
            diagnostics.append(
                Diagnostic("error", "SG100", path, f"invalid JSONL record: {exc.msg}", line_number)
            )
    return payloads, "jsonl", diagnostics


def load_dataset(
    path: str,
    *,
    label: str,
    options: CheckOptions,
    stdin: TextIO | None = None,
) -> LoadedDataset:
    """Read JSON/JSONL and build a content-free matching index."""

    options.validate()
    try:
        data, _ = _read_source(path, stdin)
    except OSError as exc:
        summary = DatasetSummary(label, path, "unknown", "0" * 64, 0, 0, 1)
        return LoadedDataset((), (Diagnostic("error", "SG100", label, str(exc), None),), summary)

    payloads, detected_format, diagnostics_list = _payloads(
        data,
        path=label,
        input_format=options.input_format,
        extension=Path(path).suffix.casefold() if path != "-" else "",
    )
    records: list[Record] = []
    invalid = sum(1 for diagnostic in diagnostics_list if diagnostic.severity == "error")
    for ordinal, (line, value) in enumerate(payloads, start=1):
        record, diagnostic = _record_from_value(
            value,
            dataset=label,
            line=line,
            ordinal=ordinal,
            options=options,
        )
        if diagnostic is not None:
            diagnostics_list.append(diagnostic)
            if diagnostic.severity == "error":
                invalid += 1
        if record is not None:
            records.append(record)
    summary = DatasetSummary(
        label=label,
        path=path,
        input_format=detected_format,
        sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data),
        records=len(records),
        invalid_records=invalid,
    )
    return LoadedDataset(tuple(records), tuple(diagnostics_list), summary)


@dataclass
class _Index:
    strict: dict[str, list[int]]
    normalized: dict[str, list[int]]
    shingles: dict[str, list[int]]


def _index(records: Sequence[Record]) -> _Index:
    strict: dict[str, list[int]] = defaultdict(list)
    normalized: dict[str, list[int]] = defaultdict(list)
    shingles: dict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        strict[record.strict_digest].append(index)
        normalized[record.normalized_digest].append(index)
        for shingle in record.shingles:
            shingles[shingle].append(index)
    return _Index(dict(strict), dict(normalized), dict(shingles))


def _similarity(left: Record, right: Record, shared: int) -> float:
    union = len(left.shingles) + len(right.shingles) - shared
    return 0.0 if union <= 0 else shared / union


def _compare_records(
    left: Sequence[Record],
    right: Sequence[Record],
    *,
    options: CheckOptions,
    scope: Literal["cross", "within"],
) -> list[Finding]:
    index = _index(left)
    findings: list[Finding] = []
    for right_index, right_record in enumerate(right):
        candidates: list[Finding] = []
        exact_indices = index.strict.get(right_record.strict_digest, [])
        for left_index in exact_indices:
            if scope == "within" and left_index >= right_index:
                continue
            candidates.append(
                Finding(
                    "exact",
                    scope,
                    left[left_index].location,
                    right_record.location,
                    1.0,
                    len(right_record.shingles),
                    left[left_index].strict_digest,
                    right_record.strict_digest,
                )
            )

        if not exact_indices:
            normalized_indices = index.normalized.get(right_record.normalized_digest, [])
            for left_index in normalized_indices:
                if scope == "within" and left_index >= right_index:
                    continue
                candidates.append(
                    Finding(
                        "normalized",
                        scope,
                        left[left_index].location,
                        right_record.location,
                        1.0,
                        len(right_record.shingles),
                        left[left_index].normalized_digest,
                        right_record.normalized_digest,
                    )
                )

        can_near_match = (
            len(right_record.shingles) > 0
            and right_record.token_count >= options.min_tokens
            and not candidates
        )
        if can_near_match:
            shared_counts: Counter[int] = Counter()
            for shingle in right_record.shingles:
                for left_index in index.shingles.get(shingle, []):
                    if scope == "within" and left_index >= right_index:
                        continue
                    shared_counts[left_index] += 1
            for left_index, shared in shared_counts.items():
                if shared < options.min_shared_shingles:
                    continue
                left_record = left[left_index]
                similarity = _similarity(left_record, right_record, shared)
                if similarity >= options.threshold:
                    candidates.append(
                        Finding(
                            "near",
                            scope,
                            left_record.location,
                            right_record.location,
                            similarity,
                            shared,
                            left_record.normalized_digest,
                            right_record.normalized_digest,
                        )
                    )

        candidates.sort(
            key=lambda finding: (
                {"exact": 0, "normalized": 1, "near": 2}[finding.kind],
                -finding.similarity,
                -finding.shared_shingles,
                finding.left.line,
            )
        )
        findings.extend(candidates[: options.max_matches])
    return findings


def check(
    left_path: str,
    right_path: str,
    *,
    options: CheckOptions | None = None,
    stdin: TextIO | None = None,
) -> CheckResult:
    """Compare two local datasets and return deterministic findings."""

    selected = options or CheckOptions()
    selected.validate()
    if left_path == "-" and right_path == "-":
        raise ValueError("only one input may be '-' (stdin)")
    left = load_dataset(left_path, label="left", options=selected, stdin=stdin)
    right = load_dataset(right_path, label="right", options=selected, stdin=stdin)
    matches = _compare_records(left.records, right.records, options=selected, scope="cross")
    if selected.within:
        matches.extend(
            _compare_records(left.records, left.records, options=selected, scope="within")
        )
        matches.extend(
            _compare_records(right.records, right.records, options=selected, scope="within")
        )
    matches.sort(
        key=lambda finding: (
            finding.scope,
            finding.left.dataset,
            finding.left.line,
            finding.right.dataset,
            finding.right.line,
            {"exact": 0, "normalized": 1, "near": 2}[finding.kind],
        )
    )
    diagnostics = left.diagnostics + right.diagnostics
    return CheckResult(left.summary, right.summary, tuple(matches), diagnostics, selected)


def iter_findings(result: CheckResult) -> Iterable[Finding]:
    """Expose findings without requiring callers to know the result layout."""

    return iter(result.matches)
