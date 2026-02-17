# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Run all tests
uv run python -m pytest tests/

# Run a single test file
uv run python -m pytest tests/test_s2_resolve.py

# Run a single test
uv run python -m pytest tests/test_s2_resolve.py::TestResolveAndFetchWorks::test_orcid_discovers_new_id

# Lint
uv run ruff check labpubs/
uv run ruff format --check labpubs/

# Type check
uv run mypy labpubs/
```

## CLI Usage

The CLI uses Click. Top-level flags (`--config`, `--verbose`) go **before** the subcommand:

```bash
uv run labpubs --config lab.yaml --verbose sync
uv run labpubs -c lab.yaml list --year 2026
uv run labpubs init members.csv --lab-name "Lab Name" --openalex-email user@example.edu
```

## Architecture

**Single entry point pattern**: All consumers (CLI, MCP server, Python library) go through `LabPubs` in `core.py`. Never write standalone scripts for tasks the package already handles.

### Data Flow

1. **Config** (`config.py`): `labpubs.yaml` → `LabPubsConfig` (Pydantic). Each researcher has `name`, `orcid`, `openalex_id`, `semantic_scholar_id`, `affiliation`, `start_date`, `end_date`, and `groups` (list of strings).

2. **Sync** (`core.py` → `_fetch_all_sources()`): For each researcher, calls `resolve_and_fetch_works()` on each backend concurrently via `asyncio.gather()`. This method:
   - Resolves current canonical author ID via ORCID (handles fragmented profiles)
   - Falls back to name-based search on S2 when ORCID lookup fails (it fails for all researchers currently)
   - Fetches papers from all discovered IDs (stored + resolved)
   - Deduplicates by source-specific paper ID
   - Returns `(works, resolved_id)` — resolved ID is persisted to DB (not YAML) via `_maybe_update_researcher_id()`

3. **Normalize** (`normalize.py`): Shared utilities — `normalize_doi()`, `normalize_title()`, `split_author_name()`. Used by `dedup.py`, `store.py`, `sources/openalex.py`, and all export modules. Do not duplicate these functions.

4. **Dedup** (`dedup.py`): Three-tier matching — DOI exact match → fuzzy title (rapidfuzz token_sort_ratio ≥ 90) → title+author+year fallback. `merge_works()` fills missing fields from new source, always takes higher citation count.

5. **Storage** (`store.py`): SQLite with WAL mode. Tables: `researchers`, `works`, `work_authors`, `researcher_works`, `funders`, `awards`, `work_awards`, `work_funders`, `linked_resources`, `sync_log`. Works are hydrated from multiple tables via `_hydrate_work()`. Researchers store `groups` as JSON text.

6. **Export** (`export/`): BibTeX, CSL-JSON, CV entries, JSON, grant reports. All read from Store.

### Source Backends (`sources/`)

All backends implement the `SourceBackend` protocol in `base.py`:

- **OpenAlex** (`openalex.py`): Uses `pyalex`. ORCID resolution via deterministic `Authors()["https://orcid.org/{orcid}"]` endpoint. Sync wraps blocking calls in `run_in_executor()`.
- **Semantic Scholar** (`semantic_scholar.py`): Uses `semanticscholar` library. ORCID resolution via `get_author(f"ORCID:{orcid}")` (currently returns 404 for all researchers). Falls back to `search_author(name)` with early termination at 5 results (the library paginates through all results otherwise). Uses `get_author_papers()` for paginated paper fetch. The `tldr` field is NOT supported by `get_author_papers()`.
- **Crossref** (`crossref.py`): Uses `habanero`. `resolve_and_fetch_works()` is a stub returning `([], None)`.

### Key Gotchas

- S2 `search_author(name, limit=5)` treats `limit` as page size, not total results — always iterate with a counter and `break` at 5.
- S2 rate limits (429) are common without an API key; the library retries automatically.
- S2 name search can produce false positives for common names (different people with same name).
- Tests use `pytest-asyncio` with `asyncio_mode = "auto"`. The `conftest.py` provides `tmp_db`, `tmp_config`, `sample_work`, `sample_work_s2` fixtures.
- Pydantic models (`models.py`) use `StrEnum` for Source and WorkType.
