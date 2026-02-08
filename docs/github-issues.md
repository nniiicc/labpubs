# GitHub Issues Integration

labpubs can create GitHub issues for new publications, allowing lab members to verify metadata and link associated code/data repositories.

## Workflow

```
labpubs sync          # fetch new publications
       |
       v
labpubs issues create # create GitHub issues for unverified pubs
       |
       v
Lab members review    # verify metadata, add code/data links
       |
       v
labpubs issues sync   # pull enrichments from closed issues
```

## Setup

1. Install and authenticate the [GitHub CLI](https://cli.github.com/):

   ```bash
   gh auth login
   ```

2. Add GitHub integration to your `labpubs.yaml`:

   ```yaml
   github_integration:
     enabled: true
     repo: mylab/publications
     author_github_map:
       "Jane Doe": janedoe
       "John Smith": jsmith42
   ```

3. Run the workflow:

   ```bash
   labpubs sync --with-issues
   ```

   Or step by step:

   ```bash
   labpubs sync
   labpubs issues create
   labpubs issues sync
   ```

## Issue Template

When a new publication is detected, labpubs creates an issue containing:

- Publication metadata (title, authors, venue, year, DOI)
- A verification checklist
- Sections for linking code repositories, datasets, and other resources
- Raw metadata in a collapsible details block

## Enrichment Parsing

When a lab member closes an issue, `labpubs issues sync` parses the issue body to extract:

- **Code repositories** -- GitHub and GitLab URLs
- **Datasets** -- Zenodo, OSF, Dataverse, and Figshare URLs
- **Verification status** -- whether the checklist was completed
- **Notes** -- free-text notes from the author

Recognized URL patterns:

| Type | Pattern |
|---|---|
| GitHub | `github.com/{owner}/{repo}` |
| GitLab | `gitlab.com/{owner}/{repo}` |
| Zenodo | `zenodo.org/record/{id}` |
| OSF | `osf.io/{id}` |
| Figshare | `figshare.com/articles/{id}` |
| DOI | `doi.org/10.*` |

## Labels

| Label | Meaning |
|---|---|
| `needs-review` | Awaiting human verification |
| `verified` | Metadata confirmed, issue processed |
| `has-code` | Code repository linked |
| `has-data` | Dataset linked |
| `not-lab-paper` | Disambiguation error |
| `author-*` | Per-author labels |
| `2024`, `2025` | Year labels |

## Verification Status

Check the current verification status:

```bash
labpubs issues status
```

List unverified publications:

```bash
labpubs list --unverified
```

List publications with linked code or data:

```bash
labpubs list --has-code
labpubs list --has-data
```
