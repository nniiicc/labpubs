# labpubs

[![PyPI version](https://img.shields.io/pypi/v/labpubs)](https://pypi.org/project/labpubs/)
[![Python](https://img.shields.io/pypi/pyversions/labpubs)](https://pypi.org/project/labpubs/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![GitHub](https://img.shields.io/github/stars/nniiicc/labpubs)](https://github.com/nniiicc/labpubs)

**labpubs** syncs publications from OpenAlex, Semantic Scholar, and Crossref into a local SQLite database, deduplicates across sources, and exports to BibTeX, CSL-JSON, CV entries, and grant reports. It includes a Click CLI, a Model Context Protocol (MCP) server, and a GitHub Issues workflow for manual verification.

## Features

- **Multi-source sync** -- query OpenAlex, Semantic Scholar, and Crossref by author ID
- **Deduplication** -- fuzzy-match titles and merge metadata across sources
- **Funding tracking** -- parse grants, funders, and award IDs from OpenAlex
- **Export formats** -- BibTeX, CSL-JSON, CV citation strings, JSON, grant reports (Markdown/CSV)
- **GitHub Issues integration** -- create verification issues per publication, parse enrichments (code/data links) from closed issues
- **MCP server** -- 17 tools for querying publications from AI assistants
- **Notifications** -- Slack and email digests for new publications

## Installation

```bash
pip install labpubs
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add labpubs
```

Optional extras:

```bash
pip install labpubs[slack]   # Slack notifications
```

## API Keys

labpubs queries three publication APIs. All are free; only Semantic Scholar requires a key:

| Source | Credential | Required | How to get |
|--------|-----------|----------|------------|
| OpenAlex | `openalex_email` | Recommended | Any email -- enters the [polite pool](https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication) for faster rate limits |
| Semantic Scholar | `semantic_scholar_api_key` | Optional | [Request a key](https://www.semanticscholar.org/product/api#api-key-form) |
| Crossref | none | -- | No credentials needed |

Add credentials to your `labpubs.yaml`:

```yaml
openalex_email: you@university.edu
semantic_scholar_api_key: your-key-here   # optional
```

## Quick Start

1. Generate a config from a CSV of lab members:

```bash
labpubs init members.csv --lab-name "My Research Lab" --openalex-email you@university.edu
```

This resolves OpenAlex and Semantic Scholar IDs from ORCIDs and writes `labpubs.yaml`. The CSV needs `name` and `orcid` columns. See `labpubs init --help` for all options.

Or create `labpubs.yaml` by hand (see [configuration docs](https://labpubs.readthedocs.io/en/latest/configuration.html)).

2. Sync publications and list results:

```bash
labpubs sync --config labpubs.yaml
labpubs list --config labpubs.yaml
```

3. Export:

```bash
labpubs export bibtex --config labpubs.yaml -o pubs.bib
labpubs export grant-report --config labpubs.yaml --format markdown
```

## Python API

```python
from labpubs import LabPubs

engine = LabPubs("labpubs.yaml")
result = engine.sync()
works = engine.list_works()
bibtex = engine.export_bibtex()
```

## CLI Reference

Run `labpubs --help` for all commands. Key commands:

| Command | Description |
|---------|-------------|
| `init` | Generate `labpubs.yaml` from a CSV of lab members |
| `sync` | Fetch new publications from upstream APIs |
| `list` | List publications with filters |
| `show` | Show detailed metadata for a work |
| `export bibtex` | Export as BibTeX |
| `export grant-report` | Generate funder/award report |
| `issues create` | Create GitHub verification issues |
| `mcp` | Start the MCP server |

## Documentation

Full documentation (configuration reference, CLI details, MCP tools, Python API) is available at [labpubs.readthedocs.io](https://labpubs.readthedocs.io) or can be built locally:

```bash
pip install labpubs[docs]
sphinx-build -b html docs docs/_build/html
```

## License

[MIT](LICENSE)
