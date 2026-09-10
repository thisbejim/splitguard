"""Deterministic overlap checks for LLM training and evaluation datasets."""

from .core import (
    CheckOptions,
    CheckResult,
    DatasetSummary,
    Diagnostic,
    Finding,
    Location,
    Record,
    check,
    iter_findings,
    load_dataset,
    normalize_text,
)

__all__ = [
    "CheckOptions",
    "CheckResult",
    "DatasetSummary",
    "Diagnostic",
    "Finding",
    "Location",
    "Record",
    "check",
    "iter_findings",
    "load_dataset",
    "normalize_text",
]

__version__ = "0.1.0"
