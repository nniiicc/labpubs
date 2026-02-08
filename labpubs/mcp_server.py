"""MCP server for labpubs using FastMCP.

Exposes lab publication data to MCP-compatible clients (Claude Desktop,
Claude Code, Cursor, etc.).
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import orjson
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from labpubs.core import LabPubs

logger = logging.getLogger(__name__)


def create_mcp_server(config_path: str | Path = "labpubs.yaml") -> FastMCP:
    """Create and configure the labpubs MCP server.

    Args:
        config_path: Path to labpubs.yaml configuration file.

    Returns:
        Configured FastMCP server instance.
    """
    mcp = FastMCP("labpubs")
    engine = LabPubs(config_path)

    @mcp.tool(
        name="labpubs_list_researchers",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_researchers() -> str:
        """List all tracked researchers with their IDs and affiliations."""
        researchers = engine.get_researchers()
        lines: list[str] = []
        for r in researchers:
            ids: list[str] = []
            if r.openalex_id:
                ids.append(f"OpenAlex: {r.openalex_id}")
            if r.orcid:
                ids.append(f"ORCID: {r.orcid}")
            if r.semantic_scholar_id:
                ids.append(f"S2: {r.semantic_scholar_id}")
            id_str = f" ({', '.join(ids)})" if ids else ""
            lines.append(f"- **{r.name}**{id_str}")
        return "\n".join(lines) if lines else "No researchers configured."

    @mcp.tool(
        name="labpubs_get_publications",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_publications(
        researcher: str | None = None,
        year: int | None = None,
        since_date: str | None = None,
        work_type: str | None = None,
        limit: int = 50,
    ) -> str:
        """Get publications for a researcher or the entire lab.

        Args:
            researcher: Name (or partial name) of a researcher.
                Omit for all lab members.
            year: Filter to a specific publication year.
            since_date: ISO date (YYYY-MM-DD). Return only works
                published after this date.
            work_type: Filter by type: journal-article,
                conference-paper, preprint, book-chapter.
            limit: Maximum number of results.
        """
        from datetime import date

        from labpubs.models import WorkType

        since = None
        if since_date:
            since = date.fromisoformat(since_date)

        wt = None
        if work_type:
            try:
                wt = WorkType(work_type)
            except ValueError:
                return f"Unknown work type: {work_type}"

        works = engine.get_works(
            researcher=researcher,
            since=since,
            year=year,
            work_type=wt,
        )

        if not works:
            return "No publications found."

        works = works[:limit]
        lines: list[str] = []
        for w in works:
            venue = w.venue or "venue unknown"
            doi = f" | DOI: {w.doi}" if w.doi else ""
            lines.append(
                f"- **{w.title}** ({w.year}) -- {venue}{doi}"
            )
        return "\n".join(lines)

    @mcp.tool(
        name="labpubs_get_new_publications",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_new_publications(days: int = 7) -> str:
        """Get publications discovered in the last N days.

        Args:
            days: Look back this many days. Default 7.
        """
        since = datetime.utcnow() - timedelta(days=days)
        works = engine.get_new_works(since)

        if not works:
            return f"No new publications in the last {days} days."

        lines = [f"New publications (last {days} days):"]
        for w in works:
            venue = w.venue or "venue unknown"
            lines.append(
                f"- **{w.title}** ({w.year}) -- {venue}"
            )
        return "\n".join(lines)

    @mcp.tool(
        name="labpubs_export_bibtex",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def export_bibtex(
        researcher: str | None = None,
        year: int | None = None,
    ) -> str:
        """Export publications as BibTeX entries.

        Args:
            researcher: Name of researcher. Omit for all.
            year: Filter to specific year. Omit for all.
        """
        return engine.export_bibtex(
            researcher=researcher, year=year
        )

    @mcp.tool(
        name="labpubs_export_cv_entries",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def export_cv_entries(
        researcher: str,
        year: int | None = None,
        style: str = "apa",
    ) -> str:
        """Generate formatted citation strings for a CV or website.

        Args:
            researcher: Name of the researcher.
            year: Filter to specific year.
            style: Citation style ('apa' or 'chicago').
        """
        entries = engine.export_cv_entries(
            researcher=researcher, year=year, style=style
        )
        if not entries:
            return "No publications found."
        return "\n\n".join(entries)

    @mcp.tool(
        name="labpubs_sync",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def sync_publications(
        researcher: str | None = None,
    ) -> str:
        """Check upstream sources for new publications.

        Args:
            researcher: Sync a specific researcher only.
                Omit to sync all.
        """
        result = await engine.sync(researcher_name=researcher)
        lines = [
            f"Sync complete at {result.timestamp.isoformat()}",
            f"Researchers checked: {result.researchers_checked}",
            f"New publications found: {len(result.new_works)}",
        ]
        if result.new_works:
            lines.append("\n**New publications:**")
            for w in result.new_works:
                venue = w.venue or "venue unknown"
                lines.append(
                    f"- {w.title} ({w.year}) -- {venue}"
                )
        if result.errors:
            lines.append(f"\nErrors: {len(result.errors)}")
            for e in result.errors:
                lines.append(f"  - {e}")
        return "\n".join(lines)

    @mcp.tool(
        name="labpubs_search",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def search_publications(
        query: str, limit: int = 20
    ) -> str:
        """Full-text search across stored publication titles and abstracts.

        Args:
            query: Search terms.
            limit: Maximum results.
        """
        works = engine.search_works(query, limit)
        if not works:
            return "No matching publications found."
        lines: list[str] = []
        for w in works:
            venue = w.venue or "venue unknown"
            lines.append(
                f"- **{w.title}** ({w.year}) -- {venue}"
            )
        return "\n".join(lines)

    @mcp.tool(
        name="labpubs_list_funders",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_funders() -> str:
        """List all funding sources with publication counts."""
        funder_counts = engine.get_funder_publication_counts()
        if not funder_counts:
            return "No funders found."
        lines: list[str] = []
        for funder, count in funder_counts:
            lines.append(
                f"- **{funder.name}** ({count} publications)"
            )
        return "\n".join(lines)

    @mcp.tool(
        name="labpubs_list_awards",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_awards(
        funder: str | None = None,
    ) -> str:
        """List all awards/grants associated with lab publications.

        Args:
            funder: Filter by funder name (e.g., "NSF").
        """
        award_list = engine.get_awards(funder)
        if not award_list:
            return "No awards found."
        lines: list[str] = []
        for a in award_list:
            funder_name = a.funder.name if a.funder else "Unknown"
            grant_id = a.funder_award_id or "N/A"
            name = a.display_name or "Untitled"
            lines.append(
                f"- [{grant_id}] **{name}** -- {funder_name}"
                f" ({a.start_year or '?'})"
            )
        return "\n".join(lines)

    @mcp.tool(
        name="labpubs_get_award_details",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_award_details(award_id: str) -> str:
        """Get detailed information about a specific award/grant.

        Args:
            award_id: Grant number (e.g., "2043024") or
                OpenAlex award ID.
        """
        award = engine.get_award_details(award_id)
        if award is None:
            return f"No award found with ID: {award_id}"
        lines = [
            f"**Award ID:** {award.funder_award_id}",
            f"**Title:** {award.display_name or 'N/A'}",
        ]
        if award.funder:
            lines.append(f"**Funder:** {award.funder.name}")
        if award.amount:
            lines.append(f"**Amount:** ${award.amount:,}")
        if award.start_year:
            lines.append(f"**Start Year:** {award.start_year}")
        if award.lead_investigator:
            li = award.lead_investigator
            name = (
                f"{li.given_name or ''} {li.family_name or ''}"
            ).strip()
            lines.append(f"**PI:** {name}")
            if li.orcid:
                lines.append(f"**PI ORCID:** {li.orcid}")
        if award.description:
            lines.append(f"\n{award.description}")
        works = engine.get_works_by_award(award_id)
        lines.append(f"\n**Publications:** {len(works)}")
        for w in works:
            lines.append(f"- {w.title} ({w.year})")
        return "\n".join(lines)

    @mcp.tool(
        name="labpubs_get_publications_by_grant",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_publications_by_grant(
        funder: str | None = None,
        award_id: str | None = None,
    ) -> str:
        """Get publications associated with a funder or grant.

        Args:
            funder: Funder name (e.g., "NSF").
            award_id: Specific grant/award number.
        """
        if award_id:
            works = engine.get_works_by_award(award_id)
        elif funder:
            works = engine.get_works_by_funder(funder)
        else:
            return "Provide funder or award_id."
        if not works:
            return "No publications found."
        lines: list[str] = []
        for w in works:
            venue = w.venue or "venue unknown"
            doi = f" | DOI: {w.doi}" if w.doi else ""
            lines.append(
                f"- **{w.title}** ({w.year}) -- {venue}{doi}"
            )
        return "\n".join(lines)

    @mcp.tool(
        name="labpubs_export_grant_report",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def export_grant_report(
        funder: str | None = None,
        award_id: str | None = None,
        report_format: str = "markdown",
    ) -> str:
        """Generate a grant report for funder reporting.

        Args:
            funder: Funder name.
            award_id: Specific grant number.
            report_format: 'markdown', 'json', or 'csv'.
        """
        return engine.make_grant_report(
            funder=funder,
            award_id=award_id,
            report_format=report_format,
        )

    @mcp.tool(
        name="labpubs_verification_status",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def verification_status() -> str:
        """Show how many publications need verification."""
        stats = engine.get_verification_stats()
        lines = [
            f"**Total publications:** {stats['total']}",
            f"**Verified:** {stats['verified']}",
            f"**Unverified:** {stats['unverified']}",
            f"**With code:** {stats['has_code']}",
            f"**With data:** {stats['has_data']}",
        ]
        return "\n".join(lines)

    @mcp.tool(
        name="labpubs_list_unverified",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_unverified(
        author: str | None = None,
    ) -> str:
        """List publications awaiting verification.

        Args:
            author: Filter to a specific author's papers.
        """
        works = engine.get_unverified_works()
        if author:
            works = [
                w
                for w in works
                if any(
                    author.lower() in a.name.lower()
                    for a in w.authors
                )
            ]
        if not works:
            return "All publications are verified."
        lines: list[str] = []
        for w in works:
            venue = w.venue or "venue unknown"
            lines.append(
                f"- **{w.title}** ({w.year}) -- {venue}"
            )
        return "\n".join(lines)

    @mcp.tool(
        name="labpubs_get_linked_resources",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_linked_resources(
        resource_type: str | None = None,
        author: str | None = None,
    ) -> str:
        """Get code repos and datasets linked to publications.

        Args:
            resource_type: Filter by type: 'code', 'dataset',
                or 'other'.
            author: Filter to a specific author.
        """
        if resource_type == "code":
            works = engine.get_works_with_code()
        elif resource_type == "dataset":
            works = engine.get_works_with_data()
        else:
            works = engine.get_works()
            works = [
                w for w in works if w.linked_resources
            ]

        if author:
            works = [
                w
                for w in works
                if any(
                    author.lower() in a.name.lower()
                    for a in w.authors
                )
            ]

        if not works:
            return "No linked resources found."

        lines: list[str] = []
        for w in works:
            lines.append(f"**{w.title}** ({w.year})")
            for res in w.linked_resources:
                if resource_type and res.resource_type != resource_type:
                    continue
                lines.append(
                    f"  - [{res.resource_type}] {res.url}"
                )
        return "\n".join(lines)

    @mcp.tool(
        name="labpubs_create_issue",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def create_verification_issue(doi: str) -> str:
        """Create a verification issue for a publication.

        Args:
            doi: DOI of the publication.
        """
        result = engine.store.find_work_by_doi(doi)
        if result is None:
            return f"No publication found with DOI: {doi}"

        work_id, work = result
        gh_config = engine.config.github_integration
        if gh_config is None or not gh_config.enabled:
            return "GitHub integration not configured."

        from labpubs.github_issues import (
            create_github_issue,
            get_issue_assignees,
            get_issue_labels,
            render_issue_body,
            render_issue_title,
        )

        title = render_issue_title(work)
        body = render_issue_body(work, gh_config)
        labels = get_issue_labels(work, gh_config)
        assignees = get_issue_assignees(work, gh_config)

        url = create_github_issue(
            gh_config.repo, title, body, labels, assignees
        )
        if url:
            return f"Issue created: {url}"
        return "Failed to create issue. Check gh CLI auth."

    @mcp.tool(
        name="labpubs_sync_issues",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def sync_issues() -> str:
        """Sync enrichments from closed GitHub issues."""
        stats = await engine.sync_github_issues()
        return (
            f"Processed: {stats['processed']}, "
            f"Updated: {stats['updated']}, "
            f"Invalid: {stats['invalid']}"
        )

    @mcp.resource("labpubs://researchers")
    async def researchers_resource() -> str:
        """List of all tracked lab researchers as JSON."""
        researchers = engine.get_researchers()
        return orjson.dumps(
            [r.model_dump() for r in researchers],
            option=orjson.OPT_INDENT_2,
        ).decode()

    @mcp.resource("labpubs://works/{researcher_name}")
    async def researcher_works_resource(
        researcher_name: str,
    ) -> str:
        """All publications for a specific researcher as JSON."""
        works = engine.get_works(researcher=researcher_name)
        return orjson.dumps(
            [w.model_dump(mode="json") for w in works],
            option=orjson.OPT_INDENT_2,
        ).decode()

    return mcp
