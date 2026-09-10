"""Human and machine-readable reports for splitguard."""

from __future__ import annotations

import json
from typing import Any

from .core import CheckResult, Finding

_RULES = {
    "SG001": (
        "Exact overlap",
        "Two records have the same canonical content after Unicode and whitespace normalization.",
    ),
    "SG002": (
        "Normalized overlap",
        "Two records match after case-folding the canonical content.",
    ),
    "SG003": (
        "Near overlap",
        "Two records share enough word shingles to exceed the configured similarity threshold.",
    ),
}


def _digest(value: str) -> str:
    return value if len(value) <= 16 else f"{value[:12]}…"


def render_json(result: CheckResult, *, include_ids: bool = False, strict: bool = False) -> str:
    payload = result.to_dict(include_ids=include_ids)
    payload["status"] = result.status(strict=strict)
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _location_text(finding: Finding, *, include_ids: bool) -> str:
    left_id = f" id={finding.left.record_id!r}" if include_ids and finding.left.record_id else ""
    right_id = f" id={finding.right.record_id!r}" if include_ids and finding.right.record_id else ""
    return (
        f"{finding.left.dataset} line {finding.left.line} (record {finding.left.ordinal}{left_id}) "
        f"↔ {finding.right.dataset} line {finding.right.line} "
        f"(record {finding.right.ordinal}{right_id})"
    )


def render_text(result: CheckResult, *, include_ids: bool = False, strict: bool = False) -> str:
    counts = result.counts()
    lines = [f"splitguard: {result.status(strict=strict)}"]
    for summary in (result.left, result.right):
        lines.append(
            f"{summary.label}: {summary.path} ({summary.records} valid, "
            f"{summary.invalid_records} invalid, {summary.input_format}; "
            f"sha256={_digest(summary.sha256)})"
        )
    lines.append(
        "overlaps: "
        f"{counts['exact']} exact, {counts['normalized']} normalized, {counts['near']} near"
    )
    if result.matches:
        lines.append("findings:")
        for finding in result.matches:
            lines.append(
                f"  {finding.rule_id} {finding.kind} {finding.scope}: {_location_text(finding, include_ids=include_ids)} "
                f"similarity={finding.similarity:.3f} shared_shingles={finding.shared_shingles}"
            )
    if result.diagnostics:
        lines.append("diagnostics:")
        for diagnostic in result.diagnostics:
            location = f" line {diagnostic.line}" if diagnostic.line is not None else ""
            lines.append(
                f"  {diagnostic.severity.upper()} {diagnostic.code} {diagnostic.dataset}{location}: "
                f"{diagnostic.message}"
            )
    lines.append(
        "summary: "
        f"{counts['total_matches']} overlap(s), {counts['errors']} error(s), "
        f"{counts['warnings']} warning(s)"
    )
    return "\n".join(lines) + "\n"


def render_markdown(result: CheckResult, *, include_ids: bool = False, strict: bool = False) -> str:
    counts = result.counts()
    lines = [
        f"## splitguard: {result.status(strict=strict)}",
        "",
        f"- Left: `{result.left.path}` ({result.left.records} valid, {result.left.invalid_records} invalid)",
        f"- Right: `{result.right.path}` ({result.right.records} valid, {result.right.invalid_records} invalid)",
        f"- Overlaps: {counts['exact']} exact, {counts['normalized']} normalized, {counts['near']} near",
        "",
    ]
    if result.matches:
        lines.extend(
            [
                "| Rule | Scope | Left | Right | Similarity | Shared shingles |",
                "| --- | --- | --- | --- | ---: | ---: |",
            ]
        )
        for finding in result.matches:
            left = f"{finding.left.dataset}:{finding.left.line}"
            right = f"{finding.right.dataset}:{finding.right.line}"
            if include_ids and finding.left.record_id:
                left += f" ({finding.left.record_id})"
            if include_ids and finding.right.record_id:
                right += f" ({finding.right.record_id})"
            lines.append(
                f"| {finding.rule_id} | {finding.scope} | `{left}` | `{right}` | "
                f"{finding.similarity:.3f} | {finding.shared_shingles} |"
            )
    else:
        lines.append("No overlaps found.")
    if result.diagnostics:
        lines.extend(["", "### Diagnostics", ""])
        for diagnostic in result.diagnostics:
            location = f" line {diagnostic.line}" if diagnostic.line is not None else ""
            lines.append(
                f"- **{diagnostic.severity.upper()} {diagnostic.code}** `{diagnostic.dataset}{location}` — {diagnostic.message}"
            )
    return "\n".join(lines) + "\n"


def render_sarif(result: CheckResult, *, strict: bool = False) -> str:
    results: list[dict[str, Any]] = []
    for finding in result.matches:
        rule_name, description = _RULES[finding.rule_id]
        results.append(
            {
                "ruleId": finding.rule_id,
                "level": "error",
                "message": {
                    "text": (
                        f"{rule_name}: {finding.left.dataset} line {finding.left.line} overlaps "
                        f"{finding.right.dataset} line {finding.right.line} "
                        f"(similarity {finding.similarity:.3f})"
                    )
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": result.left.path},
                            "region": {"startLine": finding.left.line},
                        }
                    }
                ],
                "relatedLocations": [
                    {
                        "id": 1,
                        "physicalLocation": {
                            "artifactLocation": {"uri": result.right.path},
                            "region": {"startLine": finding.right.line},
                        },
                    }
                ],
                "fingerprints": {"splitguard/v1": finding.fingerprint()},
                "properties": {
                    "scope": finding.scope,
                    "similarity": round(finding.similarity, 6),
                    "shared_shingles": finding.shared_shingles,
                    "description": description,
                },
            }
        )
    for diagnostic in result.diagnostics:
        if diagnostic.severity == "info":
            continue
        result_item: dict[str, Any] = {
            "ruleId": diagnostic.code,
            "level": "error" if diagnostic.severity == "error" or strict else "warning",
            "message": {"text": diagnostic.message},
            "properties": {"dataset": diagnostic.dataset},
        }
        if diagnostic.line is not None:
            path = (
                result.left.path if diagnostic.dataset == result.left.label else result.right.path
            )
            result_item["locations"] = [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": path},
                        "region": {"startLine": diagnostic.line},
                    }
                }
            ]
        results.append(result_item)

    rules = [
        {"id": rule_id, "name": name, "shortDescription": {"text": description}}
        for rule_id, (name, description) in _RULES.items()
    ]
    for diagnostic in result.diagnostics:
        if diagnostic.code not in {rule["id"] for rule in rules}:
            rules.append(
                {
                    "id": diagnostic.code,
                    "name": diagnostic.code,
                    "shortDescription": {"text": diagnostic.message},
                }
            )
    payload = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "splitguard", "version": "0.1.0", "rules": rules}},
                "results": results,
                "properties": {"status": result.status(strict=strict), "schema_version": 1},
            }
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
