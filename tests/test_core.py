from __future__ import annotations

import json
from pathlib import Path

import pytest

from splitguard import CheckOptions, check, normalize_text
from splitguard.report import render_json, render_markdown, render_sarif, render_text


def write_jsonl(path: Path, rows: list[object]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_normalize_text_handles_unicode_whitespace_and_case() -> None:
    assert normalize_text("  Café\u00a0\r\n  LATTE ", "text") == "café latte"
    assert normalize_text("  Café\u00a0\r\n  LATTE ", "strict") == "Café LATTE"


def test_chat_messages_are_compared_without_ids(tmp_path: Path) -> None:
    left = tmp_path / "train.jsonl"
    right = tmp_path / "eval.jsonl"
    row = {
        "id": "private-train-id",
        "messages": [
            {"role": "user", "content": "Explain deterministic fixtures."},
            {"role": "assistant", "content": "They make tests repeatable."},
        ],
    }
    write_jsonl(left, [row])
    write_jsonl(right, [{**row, "id": "private-eval-id"}])

    result = check(str(left), str(right))

    assert result.status() == "FAIL"
    assert len(result.matches) == 1
    assert result.matches[0].kind == "exact"
    assert result.matches[0].left.record_id == "private-train-id"
    payload = json.loads(render_json(result))
    assert "id" not in payload["matches"][0]["left"]
    assert "deterministic fixtures" not in render_json(result)
    shown = json.loads(render_json(result, include_ids=True))
    assert shown["matches"][0]["left"]["id"] == "private-train-id"


def test_case_only_difference_is_normalized_overlap(tmp_path: Path) -> None:
    left = tmp_path / "a.jsonl"
    right = tmp_path / "b.jsonl"
    write_jsonl(left, [{"prompt": "A Stable Prompt", "completion": "A Stable Answer"}])
    write_jsonl(right, [{"prompt": "a stable prompt", "completion": "a stable answer"}])

    result = check(str(left), str(right))

    assert [finding.kind for finding in result.matches] == ["normalized"]


def test_near_overlap_uses_shingles_and_threshold(tmp_path: Path) -> None:
    left = tmp_path / "a.jsonl"
    right = tmp_path / "b.jsonl"
    base = (
        "The evaluator records every request and response in a deterministic fixture so a model "
        "migration can be replayed locally without an API key or a network connection."
    )
    changed = base.replace("network connection", "network dependency")
    write_jsonl(left, [{"id": "a", "text": base}])
    write_jsonl(right, [{"id": "b", "text": changed}])

    result = check(
        str(left),
        str(right),
        options=CheckOptions(threshold=0.8, min_tokens=10, shingle_size=4, min_shared_shingles=3),
    )

    assert len(result.matches) == 1
    assert result.matches[0].kind == "near"
    assert result.matches[0].similarity >= 0.8


def test_within_reports_each_pair_once(tmp_path: Path) -> None:
    left = tmp_path / "a.jsonl"
    right = tmp_path / "b.jsonl"
    write_jsonl(left, [{"text": "same"}, {"text": "same"}])
    write_jsonl(right, [{"text": "different"}])

    result = check(str(left), str(right), options=CheckOptions(within=True, min_tokens=1))

    assert {
        (finding.scope, finding.left.line, finding.right.line) for finding in result.matches
    } == {("within", 1, 2)}


def test_explicit_field_supports_dotted_paths_and_custom_shapes(tmp_path: Path) -> None:
    left = tmp_path / "a.jsonl"
    right = tmp_path / "b.jsonl"
    write_jsonl(left, [{"payload": {"question": "What is a reproducible test?"}}])
    write_jsonl(right, [{"payload": {"question": "What is a reproducible test?"}}])

    result = check(str(left), str(right), options=CheckOptions(fields=("payload.question",)))

    assert len(result.matches) == 1
    assert result.matches[0].kind == "exact"


def test_sharegpt_and_tool_call_content_are_canonicalized(tmp_path: Path) -> None:
    left = tmp_path / "sharegpt.jsonl"
    right = tmp_path / "openai.jsonl"
    write_jsonl(
        left,
        [
            {
                "conversations": [
                    {"from": "human", "value": "Book a flight."},
                    {
                        "from": "gpt",
                        "value": "I will check availability.",
                        "tool_calls": [
                            {"function": {"name": "search", "arguments": {"to": "MEL"}}}
                        ],
                    },
                ]
            }
        ],
    )
    write_jsonl(
        right,
        [
            {
                "messages": [
                    {"role": "user", "content": "Book a flight."},
                    {
                        "role": "assistant",
                        "content": "I will check availability.",
                        "tool_calls": [
                            {"function": {"name": "search", "arguments": {"to": "MEL"}}}
                        ],
                    },
                ]
            }
        ],
    )

    result = check(str(left), str(right))

    assert len(result.matches) == 1
    assert result.matches[0].kind == "exact"


def test_malformed_and_unrecognized_records_are_reported(tmp_path: Path) -> None:
    left = tmp_path / "bad.jsonl"
    right = tmp_path / "right.jsonl"
    left.write_text(
        '{"prompt":"ok"}\nnot-json\n42\n{"metadata":{"source":"x"}}\n', encoding="utf-8"
    )
    write_jsonl(right, [{"prompt": "other"}])

    result = check(str(left), str(right))

    assert result.left.records == 1
    assert result.left.invalid_records == 2
    assert {diagnostic.code for diagnostic in result.diagnostics} == {"SG100", "SG101", "SG102"}
    assert result.status() == "FAIL"
    assert result.status(strict=True) == "FAIL"


def test_json_array_and_pretty_object_auto_detection(tmp_path: Path) -> None:
    array = tmp_path / "array.json"
    pretty = tmp_path / "pretty.json"
    right = tmp_path / "right.jsonl"
    array.write_text(json.dumps([{"text": "one"}, {"text": "two"}]), encoding="utf-8")
    pretty.write_text(json.dumps({"text": "one"}, indent=2), encoding="utf-8")
    write_jsonl(right, [{"text": "one"}])

    array_result = check(str(array), str(right))
    pretty_result = check(str(pretty), str(right))

    assert array_result.left.input_format == "json"
    assert array_result.left.records == 2
    assert pretty_result.left.input_format == "json"
    assert len(pretty_result.matches) == 1


def test_reports_are_machine_and_review_friendly(tmp_path: Path) -> None:
    left = tmp_path / "a.jsonl"
    right = tmp_path / "b.jsonl"
    write_jsonl(left, [{"text": "a repeated record"}])
    write_jsonl(right, [{"text": "a repeated record"}])
    result = check(str(left), str(right))

    text = render_text(result)
    markdown = render_markdown(result)
    sarif = json.loads(render_sarif(result))
    assert "SG001 exact cross" in text
    assert "| SG001 | cross |" in markdown
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["results"][0]["ruleId"] == "SG001"
    assert (
        sarif["runs"][0]["results"][0]["relatedLocations"][0]["physicalLocation"]["region"][
            "startLine"
        ]
        == 1
    )


def test_stdin_is_supported_for_one_side(tmp_path: Path) -> None:
    right = tmp_path / "right.jsonl"
    write_jsonl(right, [{"text": "from stdin"}])

    from io import StringIO

    result = check("-", str(right), stdin=StringIO('{"text":"from stdin"}\n'))

    assert len(result.matches) == 1


def test_invalid_options_fail_fast() -> None:
    with pytest.raises(ValueError, match="threshold"):
        CheckOptions(threshold=0).validate()
