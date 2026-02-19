"""Core orchestration engine for labpubs.

Ties together sources, storage, deduplication, and export. This is the
single entry point used by all consumer interfaces (CLI, MCP, library).
"""

import asyncio
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from labpubs.config import LabPubsConfig, ResearcherConfig, load_config
from labpubs.dedup import find_match, merge_works
from labpubs.export.bibtex import works_to_bibtex
from labpubs.export.csl_json import works_to_csl_json
from labpubs.export.cv_entries import works_to_cv_entries
from labpubs.export.grant_report import export_grant_report
from labpubs.export.json_export import works_to_json
from labpubs.models import (
    Author,
    Award,
    Funder,
    IngestResult,
    SyncResult,
    Work,
    WorkType,
)
from labpubs.notify.email import send_email_notification
from labpubs.notify.slack import send_slack_notification
from labpubs.sources.crossref import CrossrefBackend
from labpubs.sources.openalex import OpenAlexBackend
from labpubs.sources.semantic_scholar import SemanticScholarBackend
from labpubs.store import Store

logger = logging.getLogger(__name__)


def _init_sources(
    config: LabPubsConfig,
) -> dict[str, OpenAlexBackend | SemanticScholarBackend | CrossrefBackend]:
    """Initialize source backends based on config.

    Args:
        config: Validated configuration.

    Returns:
        Mapping of source name to backend instance.
    """
    backends: dict[str, OpenAlexBackend | SemanticScholarBackend | CrossrefBackend] = {}
    for source_name in config.sources:
        if source_name == "openalex":
            backends["openalex"] = OpenAlexBackend(email=config.openalex_email)
        elif source_name == "semantic_scholar":
            backends["semantic_scholar"] = SemanticScholarBackend(
                api_key=config.semantic_scholar_api_key
            )
        elif source_name == "crossref":
            backends["crossref"] = CrossrefBackend(email=config.openalex_email)
    return backends


class LabPubs:
    """Main orchestrator for publication tracking.

    Used by CLI, MCP server, and library consumers.
    """

    def __init__(self, config_path: str | Path = "labpubs.yaml") -> None:
        """Initialize LabPubs with a configuration file.

        Args:
            config_path: Path to the labpubs YAML config file.
        """
        self.config = load_config(config_path)
        self.store = Store(self.config.resolved_database_path)
        self.sources = _init_sources(self.config)
        self._sync_researchers()

    def _sync_researchers(self) -> None:
        """Ensure all configured researchers exist in the database."""
        for rc in self.config.researchers:
            self.store.upsert_researcher(
                name=rc.name,
                config_key=rc.name,
                openalex_id=rc.openalex_id,
                semantic_scholar_id=rc.semantic_scholar_id,
                orcid=rc.orcid,
                affiliation=rc.affiliation,
                start_date=rc.start_date,
                end_date=rc.end_date,
                groups=rc.groups,
            )

    async def sync(
        self,
        researcher_name: str | None = None,
        with_issues: bool = False,
    ) -> SyncResult:
        """Fetch new publications from upstream sources.

        Args:
            researcher_name: Sync a specific researcher only.
                Omit to sync all.
            with_issues: Also create/sync GitHub verification
                issues after fetching.

        Returns:
            SyncResult with counts and lists of new/updated works.
        """
        researchers = self.config.researchers
        if researcher_name:
            researchers = [
                r for r in researchers if researcher_name.lower() in r.name.lower()
            ]

        last_sync = self.store.get_last_sync_date()
        since_date = last_sync.date() if last_sync else None

        new_works: list[Work] = []
        updated_works: list[Work] = []
        errors: list[str] = []

        for rc in researchers:
            researcher_id = self.store.get_researcher_id(rc.name)
            if researcher_id is None:
                errors.append(f"Researcher '{rc.name}' not found in database")
                continue

            fetched = await self._fetch_all_sources(rc, since_date)
            new, updated = self._dedup_and_store(fetched, researcher_id)
            new_works.extend(new)
            updated_works.extend(updated)

        result = SyncResult(
            timestamp=datetime.utcnow(),
            researchers_checked=len(researchers),
            new_works=new_works,
            updated_works=updated_works,
            total_works=self.store.get_total_works_count(),
            errors=errors,
        )
        self.store.log_sync(result)

        if with_issues:
            await self.create_verification_issues(researcher_name)
            await self.sync_github_issues()

        return result

    async def _fetch_all_sources(
        self,
        researcher_config: ResearcherConfig,
        since: date | None,
    ) -> list[Work]:
        """Fetch works from all configured sources for one researcher.

        Uses ORCID resolution to discover current author IDs, then
        fetches from all known IDs (stored + ORCID-resolved) per source.

        Args:
            researcher_config: Researcher configuration.
            since: Optional date filter.

        Returns:
            Combined list of works from all sources.
        """
        tasks: list[tuple[str, Any]] = []

        if "openalex" in self.sources and (
            researcher_config.openalex_id or researcher_config.orcid
        ):
            tasks.append(
                (
                    "openalex",
                    self.sources["openalex"].resolve_and_fetch_works(
                        stored_id=researcher_config.openalex_id,
                        orcid=researcher_config.orcid,
                        since=since,
                        name=researcher_config.name,
                    ),
                )
            )

        if "semantic_scholar" in self.sources and (
            researcher_config.semantic_scholar_id or researcher_config.orcid
        ):
            tasks.append(
                (
                    "semantic_scholar",
                    self.sources["semantic_scholar"].resolve_and_fetch_works(
                        stored_id=researcher_config.semantic_scholar_id,
                        orcid=researcher_config.orcid,
                        since=since,
                        name=researcher_config.name,
                    ),
                )
            )

        if not tasks:
            logger.warning(
                "No source IDs or ORCID configured for researcher '%s'",
                researcher_config.name,
            )
            return []

        source_names = [t[0] for t in tasks]
        coros = [t[1] for t in tasks]
        results = await asyncio.gather(*coros, return_exceptions=True)

        all_works: list[Work] = []
        for source_name, result in zip(source_names, results):
            if isinstance(result, BaseException):
                logger.error(
                    "Source fetch failed for %s: %s",
                    source_name,
                    result,
                )
                continue
            works, resolved_id = result
            all_works.extend(works)

            if resolved_id:
                self._maybe_update_researcher_id(
                    researcher_config, source_name, resolved_id
                )

        return all_works

    def _maybe_update_researcher_id(
        self,
        researcher_config: ResearcherConfig,
        source_name: str,
        resolved_id: str,
    ) -> None:
        """Update the researcher's source ID in the DB if stale.

        Only updates the database, never the YAML config file.
        """
        if source_name == "semantic_scholar":
            stored = researcher_config.semantic_scholar_id
            if stored and stored == resolved_id:
                return
            logger.info(
                "Updating DB S2 ID for '%s': %s -> %s",
                researcher_config.name,
                stored,
                resolved_id,
            )
            self.store.update_researcher_source_id(
                config_key=researcher_config.name,
                semantic_scholar_id=resolved_id,
            )
        elif source_name == "openalex":
            stored = researcher_config.openalex_id
            if stored and stored == resolved_id:
                return
            logger.info(
                "Updating DB OpenAlex ID for '%s': %s -> %s",
                researcher_config.name,
                stored,
                resolved_id,
            )
            self.store.update_researcher_source_id(
                config_key=researcher_config.name,
                openalex_id=resolved_id,
            )

    def _dedup_and_store(
        self,
        works: list[Work],
        researcher_id: int | None = None,
    ) -> tuple[list[Work], list[Work]]:
        """Deduplicate works against existing store and persist.

        For each candidate work, checks for an existing match using
        the three-tier dedup strategy. New works are inserted, matched
        works are merged.

        Args:
            works: Candidate works to dedup and store.
            researcher_id: Optional researcher to link works to.

        Returns:
            Tuple of (new_works, updated_works).
        """
        new_works: list[Work] = []
        updated_works: list[Work] = []
        existing_works = self.store.get_all_works_for_matching()

        for work in works:
            match_id = find_match(work, existing_works)
            if match_id is None:
                work.first_seen = datetime.utcnow()
                work_id = self.store.insert_work(work)
                if researcher_id is not None:
                    self.store.link_researcher_work(researcher_id, work_id)
                new_works.append(work)
                # Add to existing for subsequent dedup checks
                surnames = [a.name.split()[-1].lower() for a in work.authors if a.name]
                existing_works.append(
                    (
                        work_id,
                        work.title.lower(),
                        work.doi,
                        work.year,
                        surnames,
                    )
                )
            else:
                existing_result = (
                    self.store.find_work_by_doi(work.doi) if work.doi else None
                )
                if existing_result is None:
                    existing_result = self.store.find_work_by_title(work.title)
                if existing_result:
                    _, existing_work = existing_result
                    merged = merge_works(existing_work, work)
                    self.store.update_work(match_id, merged)
                    if researcher_id is not None:
                        self.store.link_researcher_work(researcher_id, match_id)
                    updated_works.append(merged)

        return new_works, updated_works

    async def ingest_scholar_alerts(
        self,
        since: str | None = None,
        unseen_only: bool = True,
        dry_run: bool = False,
    ) -> IngestResult:
        """Ingest publications from Google Scholar alert emails.

        Connects to IMAP, fetches alert emails, parses publications,
        deduplicates against existing works, and persists.

        Args:
            since: Only process emails since this ISO date (unused in v1).
            unseen_only: Process only unread emails.
            dry_run: Parse and display without saving.

        Returns:
            IngestResult with counts and lists of new/updated works.
        """
        from labpubs.ingest.scholar_alerts import (
            alert_item_to_work,
            fetch_alert_emails_sync,
            match_email_to_researcher,
            parse_alert_html,
        )

        alert_config = self.config.scholar_alerts
        if not alert_config.enabled:
            return IngestResult(
                timestamp=datetime.utcnow(),
                emails_checked=0,
                items_found=0,
                errors=["Scholar alert ingestion is not enabled in config"],
            )

        # Create a copy to avoid mutating the shared config object
        if not unseen_only:
            alert_config = alert_config.model_copy(deep=True)
            alert_config.search.unseen_only = False

        loop = asyncio.get_running_loop()
        try:
            emails = await loop.run_in_executor(
                None, fetch_alert_emails_sync, alert_config
            )
        except Exception as exc:
            logger.error("Failed to fetch alert emails: %s", exc)
            return IngestResult(
                timestamp=datetime.utcnow(),
                emails_checked=0,
                items_found=0,
                errors=[f"IMAP fetch failed: {exc}"],
            )

        new_works: list[Work] = []
        updated_works: list[Work] = []
        items_found = 0
        skipped = 0
        errors: list[str] = []

        for alert_email in emails:
            # Idempotency check
            if self.store.is_alert_email_processed(alert_email.message_id):
                skipped += 1
                continue

            items = parse_alert_html(alert_email.html_body)
            items_found += len(items)

            # Determine researcher
            researcher_name = match_email_to_researcher(
                alert_email.subject,
                alert_email.html_body,
                alert_config.researcher_map,
            )
            researcher_id = (
                self.store.get_researcher_id(researcher_name)
                if researcher_name
                else None
            )

            if not dry_run:
                self.store.insert_alert_email(
                    message_id=alert_email.message_id,
                    internal_date=alert_email.internal_date,
                    gmail_uid=alert_email.gmail_uid,
                    subject=alert_email.subject,
                    from_addr=alert_email.from_addr,
                    to_addr=alert_email.to_addr,
                    raw_html=alert_email.html_body,
                )

            for item in items:
                work = alert_item_to_work(item)

                if dry_run:
                    new_works.append(work)
                    continue

                new, updated = self._dedup_and_store([work], researcher_id)
                new_works.extend(new)
                updated_works.extend(updated)

                # Determine work_id for alert item record
                work_id: int | None = None
                if new or updated:
                    title_result = self.store.find_work_by_title(work.title)
                    if title_result:
                        work_id = title_result[0]

                self.store.insert_alert_item(
                    message_id=alert_email.message_id,
                    position=item.position,
                    title=item.title,
                    authors=item.authors_raw,
                    venue=item.venue,
                    year=item.year,
                    target_url=item.target_url,
                    scholar_url=item.scholar_url,
                    work_id=work_id,
                )

        return IngestResult(
            timestamp=datetime.utcnow(),
            emails_checked=len(emails),
            items_found=items_found,
            new_works=new_works,
            updated_works=updated_works,
            skipped_emails=skipped,
            errors=errors,
        )

    def get_works(
        self,
        researcher: str | None = None,
        since: date | None = None,
        year: int | None = None,
        work_type: WorkType | None = None,
    ) -> list[Work]:
        """Query stored works with optional filters.

        Args:
            researcher: Researcher name (partial match).
            since: Filter by publication date.
            year: Filter by publication year.
            work_type: Filter by work type.

        Returns:
            List of matching Work objects.
        """
        researcher_id = None
        if researcher:
            researcher_id = self.store.get_researcher_id(researcher)
        return self.store.get_works(
            researcher_id=researcher_id,
            since=since,
            year=year,
            work_type=work_type,
        )

    def get_researchers(self) -> list[Author]:
        """Return configured researchers with their resolved IDs.

        Returns:
            List of Author objects for all tracked researchers.
        """
        return self.store.get_researchers()

    def get_new_works(self, since: datetime | None = None) -> list[Work]:
        """Return works first seen after the given timestamp.

        Args:
            since: Datetime threshold.

        Returns:
            List of recently discovered works.
        """
        return self.store.get_new_works(since)

    def search_works(self, query: str, limit: int = 20) -> list[Work]:
        """Full-text search across titles and abstracts.

        Args:
            query: Search terms.
            limit: Maximum results.

        Returns:
            Matching works.
        """
        return self.store.search_works(query, limit)

    def export_bibtex(
        self,
        researcher: str | None = None,
        year: int | None = None,
    ) -> str:
        """Export filtered works as BibTeX string.

        Args:
            researcher: Filter by researcher name.
            year: Filter by publication year.

        Returns:
            BibTeX-formatted string.
        """
        works = self.get_works(researcher=researcher, year=year)
        return works_to_bibtex(works)

    def export_csl_json(
        self,
        researcher: str | None = None,
        year: int | None = None,
    ) -> list[dict[str, Any]]:
        """Export as CSL-JSON.

        Args:
            researcher: Filter by researcher name.
            year: Filter by publication year.

        Returns:
            List of CSL-JSON dictionaries.
        """
        works = self.get_works(researcher=researcher, year=year)
        return works_to_csl_json(works)

    def export_cv_entries(
        self,
        researcher: str,
        year: int | None = None,
        style: str = "apa",
    ) -> list[str]:
        """Generate formatted citation strings for CV use.

        Args:
            researcher: Researcher name.
            year: Optional year filter.
            style: Citation style ('apa' or 'chicago').

        Returns:
            List of formatted citation strings.
        """
        works = self.get_works(researcher=researcher, year=year)
        return works_to_cv_entries(works, style)

    def export_json(
        self,
        researcher: str | None = None,
        year: int | None = None,
    ) -> list[dict[str, Any]]:
        """Export as labpubs-native JSON.

        Args:
            researcher: Filter by researcher name.
            year: Filter by publication year.

        Returns:
            List of JSON dictionaries.
        """
        works = self.get_works(researcher=researcher, year=year)
        return works_to_json(works)

    def get_works_by_funder(self, funder: str, year: int | None = None) -> list[Work]:
        """Get works funded by a specific funder.

        Args:
            funder: Funder name (partial, case-insensitive).
            year: Optional year filter.

        Returns:
            List of matching Work objects.
        """
        return self.store.get_works_by_funder(funder, year)

    def get_works_by_award(self, award_id: str) -> list[Work]:
        """Get works linked to a specific grant number.

        Args:
            award_id: Funder-assigned grant number.

        Returns:
            List of matching Work objects.
        """
        return self.store.get_works_by_award(award_id)

    def get_funders(self) -> list[Funder]:
        """List all funders in the database.

        Returns:
            List of Funder objects.
        """
        return self.store.get_all_funders()

    def get_awards(self, funder: str | None = None) -> list[Award]:
        """List awards, optionally filtered by funder.

        Args:
            funder: Filter by funder name.

        Returns:
            List of Award objects.
        """
        return self.store.get_all_awards(funder)

    def get_award_details(self, award_id: str) -> Award | None:
        """Get details for an award by grant number.

        Args:
            award_id: Funder-assigned grant number.

        Returns:
            Award or None.
        """
        return self.store.get_award_by_funder_award_id(award_id)

    def get_funder_publication_counts(
        self,
    ) -> list[tuple[Funder, int]]:
        """Get all funders with publication counts.

        Returns:
            List of (Funder, count) tuples.
        """
        return self.store.get_funder_publication_counts()

    def make_grant_report(
        self,
        funder: str | None = None,
        award_id: str | None = None,
        report_format: str = "markdown",
        include_abstract: bool = False,
    ) -> str:
        """Generate a grant report.

        Args:
            funder: Filter by funder name.
            award_id: Filter by grant number.
            report_format: 'markdown', 'json', or 'csv'.
            include_abstract: Include abstracts (markdown only).

        Returns:
            Formatted report string.
        """
        award = None
        funder_name = funder

        if award_id:
            award = self.get_award_details(award_id)
            works = self.get_works_by_award(award_id)
            if award and award.funder:
                funder_name = award.funder.name
        elif funder:
            works = self.get_works_by_funder(funder)
        else:
            works = self.get_works()

        return export_grant_report(
            works=works,
            award=award,
            funder_name=funder_name,
            report_format=report_format,
            include_abstract=include_abstract,
        )

    def get_unverified_works(self) -> list[Work]:
        """Get publications not yet verified via GitHub issues.

        Returns:
            List of unverified Work objects.
        """
        return self.store.get_unverified_works()

    def get_works_with_code(self) -> list[Work]:
        """Get publications with linked code repositories.

        Returns:
            List of Work objects with code links.
        """
        return self.store.get_works_with_code()

    def get_works_with_data(self) -> list[Work]:
        """Get publications with linked datasets.

        Returns:
            List of Work objects with dataset links.
        """
        return self.store.get_works_with_data()

    def get_verification_stats(self) -> dict[str, int]:
        """Get verification statistics.

        Returns:
            Dict with total, verified, unverified, has_code,
            has_data counts.
        """
        return self.store.get_verification_stats()

    async def create_verification_issues(
        self, researcher: str | None = None
    ) -> list[str]:
        """Create GitHub issues for unverified publications.

        Args:
            researcher: Filter by researcher name.

        Returns:
            List of created issue URLs.
        """
        from labpubs.github_issues import (
            create_github_issue,
            get_issue_assignees,
            get_issue_labels,
            render_issue_body,
            render_issue_title,
        )

        gh_config = self.config.github_integration
        if gh_config is None or not gh_config.enabled:
            logger.warning("GitHub integration not configured")
            return []

        works = self.get_unverified_works()
        if researcher:
            works = [
                w
                for w in works
                if any(researcher.lower() in a.name.lower() for a in w.authors)
            ]

        # Filter out works that already have an issue
        works = [w for w in works if not w.verification_issue_url]

        urls: list[str] = []
        for work in works:
            title = render_issue_title(work)
            body = render_issue_body(work, gh_config)
            labels = get_issue_labels(work, gh_config)
            assignees = get_issue_assignees(work, gh_config)

            url = create_github_issue(
                gh_config.repo,
                title,
                body,
                labels,
                assignees,
            )
            if url:
                urls.append(url)
                # Store the issue URL on the work
                result = self.store.find_work_by_doi(work.doi) if work.doi else None
                if result is None and work.openalex_id:
                    result = self.store.find_work_by_openalex_id(work.openalex_id)
                if result:
                    work_id, _ = result
                    self._conn_execute_issue_url(work_id, url)

        return urls

    def _conn_execute_issue_url(self, work_id: int, url: str) -> None:
        """Store the verification issue URL on a work.

        Args:
            work_id: Database row ID.
            url: GitHub issue URL.
        """
        self.store._conn.execute(
            """UPDATE works
               SET verification_issue_url = ?
               WHERE id = ?""",
            (url, work_id),
        )
        self.store._conn.commit()

    async def sync_github_issues(self) -> dict[str, int]:
        """Sync enrichments from closed GitHub issues.

        Returns:
            Dict with processed, updated, invalid counts.
        """
        from labpubs.github_issues import (
            add_issue_labels,
            enrichments_to_linked_resources,
            extract_publication_id,
            list_closed_issues,
            parse_issue_enrichments,
        )

        gh_config = self.config.github_integration
        if gh_config is None or not gh_config.enabled:
            logger.warning("GitHub integration not configured")
            return {"processed": 0, "updated": 0, "invalid": 0}

        issues = list_closed_issues(gh_config.repo, gh_config.labels.new)

        stats = {"processed": 0, "updated": 0, "invalid": 0}

        for issue in issues:
            body = issue.get("body", "")
            pub_id = extract_publication_id(body)
            if not pub_id:
                continue

            # Find the work in the database
            result = self.store.find_work_by_doi(pub_id)
            if result is None:
                result = self.store.find_work_by_openalex_id(pub_id)
            if result is None:
                continue

            work_id, work = result
            stats["processed"] += 1

            enrichments = parse_issue_enrichments(body)

            if not enrichments["is_valid"]:
                stats["invalid"] += 1
                new_labels = [gh_config.labels.invalid]
                add_issue_labels(
                    gh_config.repo,
                    issue["number"],
                    new_labels,
                )
                continue

            # Add linked resources
            resources = enrichments_to_linked_resources(enrichments)
            closed_by = issue.get("closedBy", {})
            gh_user = closed_by.get("login") if closed_by else None

            for res in resources:
                self.store.add_linked_resource(work_id, res, added_by=gh_user)

            # Mark verified
            self.store.mark_work_verified(
                work_id,
                verified_by=gh_user,
                issue_url=issue.get("url"),
                notes=enrichments.get("notes"),
            )

            # Update labels on the issue
            new_labels = [gh_config.labels.verified]
            if enrichments["code_repos"]:
                new_labels.append(gh_config.labels.has_code)
            if enrichments["datasets"]:
                new_labels.append(gh_config.labels.has_data)
            add_issue_labels(
                gh_config.repo,
                issue["number"],
                new_labels,
            )

            stats["updated"] += 1

        return stats

    async def resolve_researcher_ids(
        self, name: str, affiliation: str | None = None
    ) -> list[Author]:
        """Search upstream APIs for author ID candidates.

        Args:
            name: Author name to search.
            affiliation: Optional affiliation filter.

        Returns:
            List of candidate Author objects.
        """
        all_candidates: list[Author] = []
        for source_name, backend in self.sources.items():
            if source_name == "crossref":
                continue
            candidates = await backend.resolve_author_id(name, affiliation)
            all_candidates.extend(candidates)
        return all_candidates

    async def notify(self, days: int = 7) -> bool:
        """Send notifications about recently discovered publications.

        Args:
            days: Look back this many days for new works.

        Returns:
            True if all notifications sent successfully.
        """
        from datetime import timedelta

        since = datetime.utcnow() - timedelta(days=days)
        new_works = self.get_new_works(since)

        if not new_works:
            logger.info("No new works to notify about")
            return True

        success = True

        slack_config = self.config.notifications.slack
        if slack_config:
            result = await send_slack_notification(
                webhook_url=slack_config.webhook_url,
                works=new_works,
                channel=slack_config.channel,
            )
            if not result:
                success = False

        email_config = self.config.notifications.email
        if email_config:
            result = send_email_notification(
                smtp_host=email_config.smtp_host,
                smtp_port=email_config.smtp_port,
                from_address=email_config.from_address,
                to_addresses=email_config.to_addresses,
                works=new_works,
            )
            if not result:
                success = False

        return success
