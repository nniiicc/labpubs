# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Active dates (`start_date`, `end_date`) for lab member tracking
- Group membership for lab members (arbitrary labels like "NLP", "faculty")
- `labpubs init` command to bootstrap config from a CSV of lab members
- Source backend conversion tests (OpenAlex, Semantic Scholar, Crossref)
- Export module tests (BibTeX, CSL-JSON, CV entries, JSON)
- GitHub Actions CI workflow
- CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md
- Issue and PR templates

## [0.1.0] - 2025-02-11

### Added
- Multi-source sync from OpenAlex, Semantic Scholar, and Crossref
- Deduplication via fuzzy title matching
- Funding tracking (grants, funders, award IDs from OpenAlex)
- Export formats: BibTeX, CSL-JSON, CV citation strings, JSON, grant reports
- GitHub Issues integration for publication verification
- MCP server with 17 tools
- Slack and email notification support
- Click CLI with `sync`, `list`, `show`, `export`, `issues`, `mcp` commands

[Unreleased]: https://github.com/nniiicc/labpubs/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nniiicc/labpubs/releases/tag/v0.1.0
