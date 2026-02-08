# MCP Server

labpubs includes a [Model Context Protocol](https://modelcontextprotocol.io/) server for use with AI assistants like Claude.

## Running the Server

```bash
labpubs --config labpubs.yaml mcp
```

## Available Tools

### Publication Queries

- **labpubs_list_publications** -- List all publications with optional filters (researcher, year)
- **labpubs_search_publications** -- Full-text search across titles and abstracts
- **labpubs_get_publication** -- Get details for a single publication by DOI

### Funding Queries

- **labpubs_funders** -- List all funders
- **labpubs_awards** -- List all awards, optionally filtered by funder
- **labpubs_award_details** -- Get details for a specific award by grant number
- **labpubs_works_by_funder** -- Get publications funded by a specific funder
- **labpubs_grant_report** -- Generate a grant report in markdown, JSON, or CSV

### Verification and Issues

- **labpubs_verification_status** -- Show verification statistics (total, verified, unverified, with code, with data)
- **labpubs_list_unverified** -- List publications awaiting verification, with optional author filter
- **labpubs_get_linked_resources** -- Get code repos and datasets linked to publications
- **labpubs_create_issue** -- Create a GitHub verification issue for a publication by DOI
- **labpubs_sync_issues** -- Sync enrichments from closed GitHub issues

### Sync

- **labpubs_sync** -- Fetch new publications from upstream sources

## Resources

The MCP server also exposes resources:

- `labpubs://researchers` -- JSON list of all tracked researchers
- `labpubs://publications/{researcher_name}` -- JSON list of publications for a researcher
