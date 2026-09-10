"""Command-line interface for splitguard."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .core import CheckOptions, check
from .report import render_json, render_markdown, render_sarif, render_text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="splitguard",
        description="Find exact and near overlaps between local LLM dataset splits.",
    )
    parser.add_argument("left", help="left/training dataset path, or '-' for stdin")
    parser.add_argument("right", help="right/evaluation dataset path, or '-' for stdin")
    parser.add_argument(
        "--field",
        action="append",
        default=[],
        metavar="PATH",
        help="content field to compare (repeatable; dotted paths or JSON Pointers)",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json", "markdown", "sarif"),
        default="text",
        help="report format (default: text)",
    )
    parser.add_argument(
        "--input-format",
        choices=("auto", "json", "jsonl"),
        default="auto",
        help="input encoding for both files (default: auto)",
    )
    parser.add_argument(
        "--normalization",
        choices=("strict", "text"),
        default="text",
        help="near-match token normalization (default: text, which case-folds)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        metavar="N",
        help="minimum word-shingle Jaccard similarity for near matches (default: 0.85)",
    )
    parser.add_argument(
        "--shingle-size",
        type=int,
        default=5,
        metavar="N",
        help="number of tokens per shingle (default: 5)",
    )
    parser.add_argument(
        "--min-tokens",
        type=int,
        default=20,
        metavar="N",
        help="skip near matching records shorter than N tokens (default: 20)",
    )
    parser.add_argument(
        "--min-shared-shingles",
        type=int,
        default=3,
        metavar="N",
        help="minimum shared shingles before computing similarity (default: 3)",
    )
    parser.add_argument(
        "--max-matches",
        type=int,
        default=5,
        metavar="N",
        help="maximum findings per right-hand record (default: 5)",
    )
    parser.add_argument(
        "--within",
        action="store_true",
        help="also report duplicate and near-duplicate records within each input",
    )
    parser.add_argument(
        "--show-ids",
        action="store_true",
        help="include user-supplied record IDs in text/JSON/Markdown reports",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings as a failing result",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.left == "-" and args.right == "-":
        print("splitguard: error: only one input may be '-' (stdin)", file=sys.stderr)
        return 2
    try:
        options = CheckOptions(
            fields=tuple(args.field),
            shingle_size=args.shingle_size,
            threshold=args.threshold,
            min_tokens=args.min_tokens,
            min_shared_shingles=args.min_shared_shingles,
            max_matches=args.max_matches,
            within=args.within,
            input_format=args.input_format,
            normalization=args.normalization,
        )
        result = check(args.left, args.right, options=options, stdin=sys.stdin)
    except ValueError as exc:
        print(f"splitguard: error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        output = render_json(result, include_ids=args.show_ids, strict=args.strict)
    elif args.format == "markdown":
        output = render_markdown(result, include_ids=args.show_ids, strict=args.strict)
    elif args.format == "sarif":
        output = render_sarif(result, strict=args.strict)
    else:
        output = render_text(result, include_ids=args.show_ids, strict=args.strict)
    sys.stdout.write(output)
    return 1 if result.status(strict=args.strict) == "FAIL" else 0
