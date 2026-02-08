# Configuration

labpubs is configured via a YAML file. Pass it to the CLI with `--config` or set the `LABPUBS_CONFIG` environment variable.

## Full Configuration Reference

```yaml
# Lab metadata
lab:
  name: My Research Lab
  url: https://example.edu/mylab

# API credentials
openalex_email: you@example.edu
semantic_scholar_api_key: null  # optional

# Database location (~ is expanded)
database_path: ~/.labpubs/labpubs.db

# Researchers to track
researchers:
  - name: Jane Doe
    openalex_id: "A5012345678"
    semantic_scholar_id: "12345678"
    orcid: "0000-0001-2345-6789"
    affiliation: University of Example

  - name: John Smith
    openalex_id: "A5087654321"

# Export settings
exports:
  default_format: bibtex
  output_dir: ./exports

# Grant aliases (shorthand for grant reports)
grant_aliases:
  my-grant:
    funder: National Science Foundation
    award_id: "2345678"

# Awards to track even without publications
tracked_awards:
  - funder: National Science Foundation
    award_id: "2345678"

# GitHub Issues integration
github_integration:
  enabled: true
  repo: mylab/publications

  # Map author names to GitHub usernames
  author_github_map:
    "Jane Doe": janedoe
    "John Smith": jsmith42

  # Label configuration
  labels:
    new: needs-review
    verified: verified
    has_code: has-code
    has_data: has-data
    invalid: not-lab-paper

  year_labels: true    # auto-create year labels (2024, 2025, ...)
  author_labels: true  # auto-create author-* labels

# Notification settings
notifications:
  email:
    enabled: false
    smtp_host: smtp.example.edu
    smtp_port: 587
    from_address: labpubs@example.edu
    to_addresses:
      - lab@example.edu
  slack:
    enabled: false
    webhook_url: https://hooks.slack.com/services/...
```

## Researcher Configuration

Each researcher entry requires at least a `name` and one identifier:

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Display name |
| `openalex_id` | No | OpenAlex author ID (e.g., `A5012345678`) |
| `semantic_scholar_id` | No | Semantic Scholar author ID |
| `orcid` | No | ORCID identifier |
| `affiliation` | No | Institutional affiliation |

At least one of `openalex_id`, `semantic_scholar_id`, or `orcid` should be provided for publication discovery to work.

## GitHub Integration

The GitHub integration uses the `gh` CLI for API access. Ensure `gh` is installed and authenticated:

```bash
gh auth status
```

See {doc}`github-issues` for the full workflow.
