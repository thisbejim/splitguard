from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def write_jsonl(path: Path, rows: list[object]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "splitguard", *args],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_exit_codes_and_formats(tmp_path: Path) -> None:
    left = tmp_path / "left.jsonl"
    right = tmp_path / "right.jsonl"
    write_jsonl(left, [{"id": "left", "text": "same record"}])
    write_jsonl(right, [{"id": "right", "text": "same record"}])

    text = run_cli(str(left), str(right))
    assert text.returncode == 1
    assert "splitguard: FAIL" in text.stdout
    assert "id=" not in text.stdout

    payload = run_cli(str(left), str(right), "--format", "json", "--show-ids")
    assert payload.returncode == 1
    parsed = json.loads(payload.stdout)
    assert parsed["matches"][0]["left"]["id"] == "left"

    sarif = run_cli(str(left), str(right), "--format", "sarif")
    assert sarif.returncode == 1
    assert json.loads(sarif.stdout)["runs"][0]["results"]


def test_cli_passes_and_strict_warnings(tmp_path: Path) -> None:
    left = tmp_path / "left.jsonl"
    right = tmp_path / "right.jsonl"
    write_jsonl(left, [{"metadata": {"source": "only"}}])
    write_jsonl(right, [{"text": "different"}])

    normal = run_cli(str(left), str(right))
    strict = run_cli(str(left), str(right), "--strict")
    assert normal.returncode == 0
    assert "splitguard: WARN" in normal.stdout
    assert strict.returncode == 1
    assert "splitguard: FAIL" in strict.stdout


def test_cli_rejects_two_stdin_inputs() -> None:
    result = run_cli("-", "-")
    assert result.returncode == 2
    assert "only one input" in result.stderr
