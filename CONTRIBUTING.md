# Contributing

Thanks for helping keep `splitguard` focused and deterministic.

Before opening a pull request:

```console
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
```

Keep runtime dependencies at zero unless a dependency is essential to the
documented core workflow. New matching behavior should include synthetic
fixtures and explain its false-positive/false-negative boundary. Do not add
real prompts, credentials, private traces, or proprietary datasets to tests.

Changes that alter the JSON report shape, finding codes, or exit statuses must
update the versioned documentation and include a migration note.
