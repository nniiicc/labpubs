"""CLI interface for labpubs using Click.

Wraps the core engine for use in cron jobs, CI pipelines, and
interactive terminal use.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import TYPE_CHECKING

import click
import orjson

from labpubs.core import LabPubs

if TYPE_CHECKING:
    from labpubs.resolve import ResolveResult

logger = logging.getLogger(__name__)


def _get_engine(config: str) -> LabPubs:
    """Create a LabPubs engine from a config path.

    Args:
        config: Path to labpubs.yaml.

    Returns:
        Initialized LabPubs instance.
    """
    try:
        return LabPubs(config)
    except FileNotFoundError:
        click.echo(f"Error: Config file not found: {config}", err=True)
        sys.exit(1)


@click.group()
@click.option(
    "-c",
    "--config",
    default="labpubs.yaml",
    help="Path to labpubs.yaml",
    type=click.Path(),
)
@click.option("--verbose", is_flag=True, help="Enable debug logging.")
@click.pass_context
def main(ctx: click.Context, config: str, verbose: bool) -> None:
    """labpubs -- Publication tracking for research labs."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")
    ctx.ensure_object(dict)
    ctx.obj["config"] = config


@main.command()
@click.option("--researcher", default=None, help="Sync a specific researcher.")
@click.option(
    "--with-issues",
    is_flag=True,
    help="Also create/sync GitHub verification issues.",
)
@click.pass_context
def sync(
    ctx: click.Context,
    researcher: str | None,
    with_issues: bool,
) -> None:
    """Fetch new publications from upstream sources."""
    engine = _get_engine(ctx.obj["config"])
    result = asyncio.run(
        engine.sync(
            researcher_name=researcher,
            with_issues=with_issues,
        )
    )

    click.echo(f"Sync complete at {result.timestamp.isoformat()}")
    click.echo(f"Researchers checked: {result.researchers_checked}")
    click.echo(f"New publications: {len(result.new_works)}")
    click.echo(f"Updated: {len(result.updated_works)}")
    click.echo(f"Total in database: {result.total_works}")

    if result.new_works:
        click.echo("\nNew publications:")
        for w in result.new_works:
            venue = w.venue or "venue unknown"
            click.echo(f"  - {w.title} ({w.year}) -- {venue}")

    if result.errors:
        click.echo(f"\nErrors ({len(result.errors)}):")
        for e in result.errors:
            click.echo(f"  - {e}")


@main.command("list")
@click.option("--researcher", default=None, help="Filter by researcher.")
@click.option("--year", default=None, type=int, help="Filter by year.")
@click.option("--new", "show_new", is_flag=True, help="Show only new works.")
@click.option(
    "--days",
    default=7,
    type=int,
    help="Days to look back for --new.",
)
@click.option("--funder", default=None, help="Filter by funder name.")
@click.option("--award-id", default=None, help="Filter by grant number.")
@click.option(
    "--unverified",
    is_flag=True,
    help="Show only unverified works.",
)
@click.option(
    "--has-code",
    is_flag=True,
    help="Show only works with linked code.",
)
@click.option(
    "--has-data",
    is_flag=True,
    help="Show only works with linked datasets.",
)
@click.pass_context
def list_works(
    ctx: click.Context,
    researcher: str | None,
    year: int | None,
    show_new: bool,
    days: int,
    funder: str | None,
    award_id: str | None,
    unverified: bool,
    has_code: bool,
    has_data: bool,
) -> None:
    """List publications with optional filters."""
    engine = _get_engine(ctx.obj["config"])

    if show_new:
        from datetime import datetime, timedelta

        since = datetime.utcnow() - timedelta(days=days)
        works = engine.get_new_works(since)
    elif unverified:
        works = engine.get_unverified_works()
    elif has_code:
        works = engine.get_works_with_code()
    elif has_data:
        works = engine.get_works_with_data()
    elif funder:
        works = engine.get_works_by_funder(funder, year)
    elif award_id:
        works = engine.get_works_by_award(award_id)
    else:
        works = engine.get_works(researcher=researcher, year=year)

    if not works:
        click.echo("No publications found.")
        return

    for w in works:
        venue = w.venue or "venue unknown"
        doi = f" DOI: {w.doi}" if w.doi else ""
        click.echo(f"  {w.title} ({w.year}) -- {venue}{doi}")


@main.command()
@click.argument("query")
@click.pass_context
def show(ctx: click.Context, query: str) -> None:
    """Show detailed metadata for a specific work (by DOI or title)."""
    engine = _get_engine(ctx.obj["config"])

    works = engine.search_works(query, limit=1)
    if not works:
        click.echo("No matching work found.")
        return

    w = works[0]
    click.echo(f"Title: {w.title}")
    click.echo(f"Year: {w.year}")
    click.echo(f"Type: {w.work_type.value}")
    click.echo(f"Venue: {w.venue or 'unknown'}")
    click.echo(f"DOI: {w.doi or 'none'}")
    click.echo(f"Authors: {', '.join(a.name for a in w.authors)}")
    if w.abstract:
        click.echo(f"\nAbstract: {w.abstract}")
    if w.tldr:
        click.echo(f"\nTLDR: {w.tldr}")
    click.echo(f"\nOpen Access: {w.open_access_url or 'no'}")
    click.echo(f"Citations: {w.citation_count or 0}")
    click.echo(f"Sources: {', '.join(s.value for s in w.sources)}")


@main.command()
@click.pass_context
def researchers(ctx: click.Context) -> None:
    """List tracked researchers and their IDs."""
    engine = _get_engine(ctx.obj["config"])
    for r in engine.get_researchers():
        ids: list[str] = []
        if r.openalex_id:
            ids.append(f"OpenAlex: {r.openalex_id}")
        if r.orcid:
            ids.append(f"ORCID: {r.orcid}")
        if r.semantic_scholar_id:
            ids.append(f"S2: {r.semantic_scholar_id}")
        id_str = f" ({', '.join(ids)})" if ids else ""

        # Active date range
        if r.start_date and r.end_date:
            date_str = f" [{r.start_date} \u2013 {r.end_date}]"
        elif r.start_date:
            date_str = f" [active since {r.start_date}]"
        else:
            date_str = ""

        # Group membership
        group_str = f" {{{', '.join(r.groups)}}}" if r.groups else ""

        click.echo(f"  {r.name}{id_str}{date_str}{group_str}")


@main.command()
@click.pass_context
def funders(ctx: click.Context) -> None:
    """List all funders with publication counts."""
    engine = _get_engine(ctx.obj["config"])
    funder_counts = engine.get_funder_publication_counts()
    if not funder_counts:
        click.echo("No funders found.")
        return
    for funder, count in funder_counts:
        click.echo(f"  {funder.name} ({count} publications)")


@main.command()
@click.option("--funder", default=None, help="Filter by funder name.")
@click.pass_context
def awards(ctx: click.Context, funder: str | None) -> None:
    """List all awards/grants."""
    engine = _get_engine(ctx.obj["config"])
    award_list = engine.get_awards(funder)
    if not award_list:
        click.echo("No awards found.")
        return
    for a in award_list:
        funder_name = a.funder.name if a.funder else "Unknown"
        grant_id = a.funder_award_id or "N/A"
        name = a.display_name or "Untitled"
        click.echo(f"  [{grant_id}] {name} -- {funder_name} ({a.start_year or '?'})")


@main.command("award-details")
@click.argument("award_id")
@click.pass_context
def award_details(ctx: click.Context, award_id: str) -> None:
    """Show detailed info for a grant by its award number."""
    engine = _get_engine(ctx.obj["config"])
    award = engine.get_award_details(award_id)
    if award is None:
        click.echo(f"No award found with ID: {award_id}")
        return
    click.echo(f"Award ID: {award.funder_award_id}")
    click.echo(f"Title: {award.display_name or 'N/A'}")
    if award.funder:
        click.echo(f"Funder: {award.funder.name}")
    if award.amount:
        click.echo(f"Amount: ${award.amount:,}")
    if award.start_year:
        click.echo(f"Start Year: {award.start_year}")
    if award.lead_investigator:
        li = award.lead_investigator
        name = f"{li.given_name or ''} {li.family_name or ''}".strip()
        click.echo(f"PI: {name}")
        if li.orcid:
            click.echo(f"PI ORCID: {li.orcid}")
    if award.description:
        click.echo(f"\nDescription: {award.description}")
    works = engine.get_works_by_award(award_id)
    click.echo(f"\nPublications: {len(works)}")
    for w in works:
        click.echo(f"  - {w.title} ({w.year})")


@main.group()
@click.pass_context
def issues(ctx: click.Context) -> None:
    """Manage GitHub verification issues."""


@issues.command("create")
@click.option("--researcher", default=None, help="Filter by researcher.")
@click.pass_context
def issues_create(ctx: click.Context, researcher: str | None) -> None:
    """Create GitHub issues for unverified publications."""
    engine = _get_engine(ctx.obj["config"])
    urls = asyncio.run(engine.create_verification_issues(researcher))
    if urls:
        click.echo(f"Created {len(urls)} issue(s):")
        for url in urls:
            click.echo(f"  {url}")
    else:
        click.echo("No new issues created.")


@issues.command("sync")
@click.pass_context
def issues_sync(ctx: click.Context) -> None:
    """Pull enrichments from closed GitHub issues."""
    engine = _get_engine(ctx.obj["config"])
    stats = asyncio.run(engine.sync_github_issues())
    click.echo(
        f"Processed: {stats['processed']}, "
        f"Updated: {stats['updated']}, "
        f"Invalid: {stats['invalid']}"
    )


@issues.command("status")
@click.pass_context
def issues_status(ctx: click.Context) -> None:
    """Show verification statistics."""
    engine = _get_engine(ctx.obj["config"])
    stats = engine.get_verification_stats()
    click.echo(f"Total publications: {stats['total']}")
    click.echo(f"Verified: {stats['verified']}")
    click.echo(f"Unverified: {stats['unverified']}")
    click.echo(f"With code: {stats['has_code']}")
    click.echo(f"With data: {stats['has_data']}")


@main.group()
def export() -> None:
    """Export publications (bibtex, json, csl-json, cv, grant-report)."""


@export.command()
@click.option("--researcher", default=None, help="Filter by researcher.")
@click.option("--year", default=None, type=int, help="Filter by year.")
@click.option("-o", "--output", default=None, help="Output file path.")
@click.pass_context
def bibtex(
    ctx: click.Context,
    researcher: str | None,
    year: int | None,
    output: str | None,
) -> None:
    """Export publications as BibTeX."""
    engine = _get_engine(ctx.obj["config"])
    result = engine.export_bibtex(researcher=researcher, year=year)
    if output:
        with open(output, "w") as f:
            f.write(result)
        click.echo(f"BibTeX written to {output}")
    else:
        click.echo(result)


@export.command()
@click.option("--researcher", default=None, help="Filter by researcher.")
@click.option("--year", default=None, type=int, help="Filter by year.")
@click.option("-o", "--output", default=None, help="Output file path.")
@click.pass_context
def json(
    ctx: click.Context,
    researcher: str | None,
    year: int | None,
    output: str | None,
) -> None:
    """Export publications as JSON."""
    engine = _get_engine(ctx.obj["config"])
    result = engine.export_json(researcher=researcher, year=year)
    data = orjson.dumps(result, option=orjson.OPT_INDENT_2).decode()
    if output:
        with open(output, "w") as f:
            f.write(data)
        click.echo(f"JSON written to {output}")
    else:
        click.echo(data)


@export.command("csl-json")
@click.option("--researcher", default=None, help="Filter by researcher.")
@click.option("--year", default=None, type=int, help="Filter by year.")
@click.option("-o", "--output", default=None, help="Output file path.")
@click.pass_context
def csl_json(
    ctx: click.Context,
    researcher: str | None,
    year: int | None,
    output: str | None,
) -> None:
    """Export publications as CSL-JSON."""
    engine = _get_engine(ctx.obj["config"])
    result = engine.export_csl_json(researcher=researcher, year=year)
    data = orjson.dumps(result, option=orjson.OPT_INDENT_2).decode()
    if output:
        with open(output, "w") as f:
            f.write(data)
        click.echo(f"CSL-JSON written to {output}")
    else:
        click.echo(data)


@export.command()
@click.option("--researcher", required=True, help="Researcher name.")
@click.option("--year", default=None, type=int, help="Filter by year.")
@click.option(
    "--style",
    default="apa",
    type=click.Choice(["apa", "chicago"]),
    help="Citation style.",
)
@click.pass_context
def cv(
    ctx: click.Context,
    researcher: str,
    year: int | None,
    style: str,
) -> None:
    """Export formatted citation strings for CV use."""
    engine = _get_engine(ctx.obj["config"])
    entries = engine.export_cv_entries(researcher=researcher, year=year, style=style)
    for entry in entries:
        click.echo(entry)
        click.echo()


@export.command("grant-report")
@click.option("--funder", default=None, help="Filter by funder name.")
@click.option("--award-id", default=None, help="Filter by grant number.")
@click.option(
    "--format",
    "report_format",
    default="markdown",
    type=click.Choice(["markdown", "json", "csv"]),
    help="Report format.",
)
@click.option("-o", "--output", default=None, help="Output file path.")
@click.pass_context
def grant_report(
    ctx: click.Context,
    funder: str | None,
    award_id: str | None,
    report_format: str,
    output: str | None,
) -> None:
    """Generate a grant report for funder reporting."""
    engine = _get_engine(ctx.obj["config"])
    result = engine.make_grant_report(
        funder=funder,
        award_id=award_id,
        report_format=report_format,
    )
    if output:
        with open(output, "w") as f:
            f.write(result)
        click.echo(f"Grant report written to {output}")
    else:
        click.echo(result)


@main.command()
@click.pass_context
def setup(ctx: click.Context) -> None:
    """Interactive setup: resolve author IDs, test API access."""
    engine = _get_engine(ctx.obj["config"])

    for rc in engine.config.researchers:
        if rc.openalex_id:
            click.echo(f"{rc.name}: OpenAlex ID already set ({rc.openalex_id})")
            continue

        click.echo(f"\nResolving IDs for: {rc.name}")
        candidates = asyncio.run(engine.resolve_researcher_ids(rc.name, rc.affiliation))

        if not candidates:
            click.echo("  No candidates found.")
            continue

        click.echo("  Candidates:")
        for i, c in enumerate(candidates):
            aff = c.affiliation or "no affiliation"
            click.echo(f"  [{i + 1}] {c.name} -- {aff}")
            if c.openalex_id:
                click.echo(f"      OpenAlex: {c.openalex_id}")
            if c.semantic_scholar_id:
                click.echo(f"      S2: {c.semantic_scholar_id}")

        choice = click.prompt(
            "  Select candidate (0 to skip)",
            type=int,
            default=0,
        )
        if 1 <= choice <= len(candidates):
            selected = candidates[choice - 1]
            click.echo(f"  Selected: {selected.name}")
            engine.store.upsert_researcher(
                name=rc.name,
                config_key=rc.name,
                openalex_id=selected.openalex_id,
                semantic_scholar_id=selected.semantic_scholar_id,
                orcid=selected.orcid,
                affiliation=selected.affiliation,
            )


@main.command("init")
@click.argument("csv_file", type=click.Path(exists=True))
@click.option(
    "-o",
    "--output",
    default="labpubs.yaml",
    type=click.Path(),
    help="Output path for the generated config (default: labpubs.yaml).",
)
@click.option(
    "--lab-name",
    default="",
    help="Name of the research lab.",
)
@click.option(
    "--institution",
    default="",
    help="Institution name (used for name-search fallback).",
)
@click.option(
    "--openalex-email",
    default=None,
    help="Email for OpenAlex polite pool.",
)
@click.option(
    "--s2-api-key",
    default=None,
    help="Semantic Scholar API key (optional).",
)
@click.option(
    "--merge",
    is_flag=True,
    help="Merge into an existing labpubs.yaml instead of overwriting.",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Auto-accept ORCID matches and skip ambiguous candidates.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print generated YAML to stdout without writing a file.",
)
def init_config(
    csv_file: str,
    output: str,
    lab_name: str,
    institution: str,
    openalex_email: str | None,
    s2_api_key: str | None,
    merge: bool,
    non_interactive: bool,
    dry_run: bool,
) -> None:
    """Generate labpubs.yaml from a CSV of lab members.

    CSV_FILE should contain at minimum a 'name' column. An 'orcid'
    column enables direct ID resolution. The command queries OpenAlex
    and Semantic Scholar to resolve author IDs, falling back to name
    search when ORCID lookup fails.

    \b
    Example CSV:
        name,orcid
        Jane Doe,0000-0001-2345-6789
        John Smith,0000-0002-3456-7890
    """
    from pathlib import Path

    from labpubs.resolve import (
        generate_config_yaml,
        merge_into_existing,
        resolve_researchers_from_csv,
    )
    from labpubs.sources.openalex import OpenAlexBackend
    from labpubs.sources.semantic_scholar import SemanticScholarBackend

    oa_backend = OpenAlexBackend(email=openalex_email)
    s2_backend = SemanticScholarBackend(api_key=s2_api_key)

    def progress(name: str, i: int, total: int) -> None:
        click.echo(f"[{i + 1}/{total}] Resolving {name}...")

    click.echo(f"Reading {csv_file}...")
    results: list[ResolveResult] = asyncio.run(
        resolve_researchers_from_csv(
            csv_file,
            openalex_backend=oa_backend,
            s2_backend=s2_backend,
            progress_callback=progress,
        )
    )

    # Interactive review of results.
    for r in results:
        _review_openalex(r, non_interactive)
        _review_s2(r, non_interactive)

    # Generate or merge YAML.
    if merge and Path(output).exists():
        yaml_str = merge_into_existing(output, results)
        click.echo(f"\nMerged {len(results)} researchers into {output}")
    else:
        yaml_str = generate_config_yaml(
            results,
            lab_name=lab_name,
            institution=institution,
            openalex_email=openalex_email,
        )

    if dry_run:
        click.echo("\n--- Generated YAML ---")
        click.echo(yaml_str)
    else:
        Path(output).write_text(yaml_str)
        click.echo(f"Config written to {output}")

    # Summary.
    oa_count = sum(1 for r in results if r.openalex_id)
    s2_count = sum(1 for r in results if r.semantic_scholar_id)
    click.echo(
        f"\nResolved: {oa_count}/{len(results)} OpenAlex, "
        f"{s2_count}/{len(results)} Semantic Scholar"
    )


def _review_openalex(result: ResolveResult, non_interactive: bool) -> None:
    """Review and optionally select an OpenAlex ID."""
    if result.openalex_id:
        label = "ORCID match" if result.openalex_confident else "CSV"
        click.echo(f"  {result.name}: OpenAlex {result.openalex_id} ({label})")
        return

    candidates = result.openalex_candidates
    if not candidates:
        click.echo(f"  {result.name}: no OpenAlex candidates")
        return

    if non_interactive:
        click.echo(
            f"  {result.name}: {len(candidates)} OpenAlex "
            f"candidate(s) -- skipped (non-interactive)"
        )
        return

    click.echo(f"\n  OpenAlex candidates for {result.name}:")
    for i, c in enumerate(candidates):
        aff = c.affiliation or "no affiliation"
        click.echo(f"    [{i + 1}] {c.name} -- {aff}")
        if c.openalex_id:
            click.echo(f"        ID: {c.openalex_id}")
    choice = click.prompt("    Select (0 to skip)", type=int, default=0)
    if 1 <= choice <= len(candidates):
        selected = candidates[choice - 1]
        result.openalex_id = selected.openalex_id
        click.echo(f"    Selected: {selected.name}")


def _review_s2(result: ResolveResult, non_interactive: bool) -> None:
    """Review and optionally select a Semantic Scholar ID."""
    if result.semantic_scholar_id:
        label = "ORCID match" if result.s2_confident else "CSV"
        click.echo(f"  {result.name}: S2 {result.semantic_scholar_id} ({label})")
        return

    candidates = result.s2_candidates
    if not candidates:
        click.echo(f"  {result.name}: no S2 candidates")
        return

    if non_interactive:
        click.echo(
            f"  {result.name}: {len(candidates)} S2 candidate(s) "
            f"-- skipped (non-interactive)"
        )
        return

    click.echo(f"\n  S2 candidates for {result.name}:")
    for i, c in enumerate(candidates):
        aff = c.affiliation or "no affiliation"
        click.echo(f"    [{i + 1}] {c.name} -- {aff}")
        if c.semantic_scholar_id:
            click.echo(f"        ID: {c.semantic_scholar_id}")
    choice = click.prompt("    Select (0 to skip)", type=int, default=0)
    if 1 <= choice <= len(candidates):
        selected = candidates[choice - 1]
        result.semantic_scholar_id = selected.semantic_scholar_id
        click.echo(f"    Selected: {selected.name}")


@main.group()
def ingest() -> None:
    """Ingest publications from email alerts."""


@ingest.command("scholar-alerts")
@click.option(
    "--since",
    default=None,
    help="Only process emails since this ISO date.",
)
@click.option(
    "--unseen-only/--all",
    default=False,
    help="Process all emails (default) or only unread.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Parse and display without saving to database.",
)
@click.pass_context
def scholar_alerts(
    ctx: click.Context,
    since: str | None,
    unseen_only: bool,
    dry_run: bool,
) -> None:
    """Ingest publications from Google Scholar alert emails."""
    engine = _get_engine(ctx.obj["config"])
    result = asyncio.run(
        engine.ingest_scholar_alerts(
            since=since,
            unseen_only=unseen_only,
            dry_run=dry_run,
        )
    )

    click.echo(f"Ingest complete at {result.timestamp.isoformat()}")
    click.echo(f"Emails checked: {result.emails_checked}")
    click.echo(f"Items found: {result.items_found}")
    click.echo(f"New publications: {len(result.new_works)}")
    click.echo(f"Updated: {len(result.updated_works)}")
    if result.skipped_emails:
        click.echo(f"Skipped (already processed): {result.skipped_emails}")

    if result.new_works:
        click.echo("\nNew publications:")
        for w in result.new_works:
            venue = w.venue or "venue unknown"
            click.echo(f"  - {w.title} ({w.year}) -- {venue}")

    if result.errors:
        click.echo(f"\nErrors ({len(result.errors)}):")
        for e in result.errors:
            click.echo(f"  - {e}")

    if dry_run:
        click.echo("\n(dry run -- nothing was saved)")


@main.command("mcp")
@click.pass_context
def mcp_serve(ctx: click.Context) -> None:
    """Start the MCP server (stdio transport)."""
    from labpubs.mcp_server import create_mcp_server

    config_path = ctx.obj["config"]
    server = create_mcp_server(config_path)
    server.run()


@main.command()
@click.option(
    "--days",
    default=7,
    type=int,
    help="Days to look back for new works.",
)
@click.pass_context
def notify(ctx: click.Context, days: int) -> None:
    """Send notification digest of recent new publications."""
    engine = _get_engine(ctx.obj["config"])
    success = asyncio.run(engine.notify(days=days))
    if success:
        click.echo("Notifications sent.")
    else:
        click.echo("Some notifications failed.", err=True)
        sys.exit(1)


@main.command()
@click.option("--host", default="127.0.0.1", help="Bind address.")
@click.option("--port", default=8000, type=int, help="Port number.")
@click.option("--reload", "auto_reload", is_flag=True, help="Auto-reload on changes.")
@click.pass_context
def serve(
    ctx: click.Context,
    host: str,
    port: int,
    auto_reload: bool,
) -> None:
    """Start the REST API server (requires labpubs[api])."""
    try:
        import uvicorn  # noqa: F811
    except ImportError:
        click.echo(
            "REST API dependencies not installed. Run: pip install labpubs[api]",
            err=True,
        )
        sys.exit(1)

    from labpubs.api.app import create_app

    config_path = ctx.obj["config"]
    app = create_app(config_path)
    uvicorn.run(app, host=host, port=port, reload=auto_reload)
