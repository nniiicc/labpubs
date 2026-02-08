# labpubs

Publication tracking and retrieval for research labs.

**labpubs** automatically discovers publications from [OpenAlex](https://openalex.org/), [Semantic Scholar](https://www.semanticscholar.org/), and [Crossref](https://www.crossref.org/), deduplicates across sources, and stores them locally in SQLite. It supports funding/grant tracking, multiple export formats, GitHub-based verification workflows, and an MCP server for use with AI assistants.

## Features

- Multi-source publication discovery (OpenAlex, Semantic Scholar, Crossref)
- Automatic deduplication across sources
- Funding and grant tracking
- GitHub Issues integration for human-in-the-loop verification
- Export to BibTeX, CSL-JSON, CV entries, and grant reports
- CLI interface and MCP server
- SQLite storage with no ORM dependencies

```{toctree}
:maxdepth: 2
:caption: User Guide

getting-started
configuration
cli
github-issues
mcp
```

```{toctree}
:maxdepth: 2
:caption: API Reference

api/index
```
