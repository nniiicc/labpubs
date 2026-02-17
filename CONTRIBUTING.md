# Contributing to labpubs

Thanks for your interest in contributing to labpubs! This guide will help you get started.

## Development Setup

1. Clone the repository:

```bash
git clone https://github.com/nniiicc/labpubs.git
cd labpubs
```

2. Install dependencies with [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
```

3. Verify everything works:

```bash
uv run pytest tests/ -v
uv run ruff check .
```

## Making Changes

1. Create a branch for your work:

```bash
git checkout -b my-feature
```

2. Make your changes and add tests for new functionality.

3. Run the test suite and linter before committing:

```bash
uv run pytest tests/ -v
uv run ruff check .
uv run ruff format .
```

4. Commit your changes and open a pull request against `main`.

## Code Style

- **Linter/formatter**: [ruff](https://docs.astral.sh/ruff/), configured in `pyproject.toml`
- **Line length**: 88 characters
- **Type hints**: Used throughout; run `uv run mypy labpubs/` to check
- **Import order**: Enforced by ruff (`isort` rules enabled)

## Project Structure

- `labpubs/` — Main package
  - `sources/` — API backends (OpenAlex, Semantic Scholar, Crossref)
  - `export/` — Output formats (BibTeX, CSL-JSON, CV entries, JSON)
  - `store.py` — SQLite persistence
  - `core.py` — Orchestration engine
  - `cli.py` — Click CLI
  - `mcp_server.py` — MCP server
- `tests/` — pytest test suite (mirrors `labpubs/` structure)
- `docs/` — Sphinx documentation
- `examples/` — Example configuration files

## Running a Single Test

```bash
uv run pytest tests/test_core.py::TestStoreBasics::test_insert_and_find_work -v
```

## Reporting Bugs

Please use the [GitHub issue tracker](https://github.com/nniiicc/labpubs/issues) with the bug report template.

## Questions?

Open a [discussion](https://github.com/nniiicc/labpubs/issues) or reach out to the maintainers.
