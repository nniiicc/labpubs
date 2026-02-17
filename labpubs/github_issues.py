"""GitHub issues integration for labpubs.

Creates verification issues for new publications and parses
enrichments from closed issues.
"""

import logging
import re
import subprocess
from typing import Any

import orjson

from labpubs.config import GitHubIntegrationConfig
from labpubs.models import LinkedResource, Work

logger = logging.getLogger(__name__)

# URL patterns for resource classification
_CODE_PATTERNS = re.compile(
    r"https?://(?:www\.)?(?:github|gitlab)\.com/[^\s)\]>]+"
)
_DATASET_PATTERNS = re.compile(
    r"https?://(?:www\.)?(?:"
    r"zenodo\.org/record[^\s)\]>]+|"
    r"doi\.org/10\.5281/zenodo\.[^\s)\]>]+|"
    r"osf\.io/[^\s)\]>]+|"
    r"dataverse\.[^\s)\]>]+|"
    r"figshare\.com/[^\s)\]>]+"
    r")"
)
_DOI_PATTERN = re.compile(
    r"https?://doi\.org/10\.[^\s)\]>]+"
)
_PUBLICATION_ID_PATTERN = re.compile(
    r"<!--\s*labpubs:publication_id:(\S+)\s*-->"
)


def render_issue_title(work: Work) -> str:
    """Generate a GitHub issue title for a publication.

    Args:
        work: Work to create an issue for.

    Returns:
        Issue title string.
    """
    return f"New publication: {work.title}"


def render_issue_body(
    work: Work, config: GitHubIntegrationConfig
) -> str:
    """Generate the GitHub issue body for a new publication.

    Args:
        work: Work to create an issue for.
        config: GitHub integration configuration.

    Returns:
        Markdown-formatted issue body.
    """
    authors_str = ", ".join(a.name for a in work.authors)
    doi_line = ""
    if work.doi:
        doi_line = (
            f"**DOI:** [{work.doi}]"
            f"(https://doi.org/{work.doi})  \n"
        )
    oa_line = ""
    if work.open_access_url:
        oa_line = (
            f"**Open Access:** [PDF]({work.open_access_url})\n"
        )
    source_line = ""
    if work.openalex_id:
        oa_id = work.openalex_id.split("/")[-1]
        source_line = (
            f"**Source:** OpenAlex "
            f"([{oa_id}](https://openalex.org/{oa_id}))  \n"
        )

    from datetime import date

    today = date.today().isoformat()

    pub_id = work.openalex_id or work.doi or work.title

    raw_json = orjson.dumps(
        work.model_dump(mode="json"),
        option=orjson.OPT_INDENT_2,
    ).decode()

    return f"""## New Publication Detected

**Title:** {work.title}
**Authors:** {authors_str}
**Venue:** {work.venue or "unknown"}
**Year:** {work.year or "unknown"}
{doi_line}{oa_line}
{source_line}**First detected:** {today}

---

## Verification Checklist

- [ ] Metadata is correct (title, authors, venue, year)
- [ ] This is actually a lab publication (not a disambiguation error)
- [ ] Not a duplicate of an existing entry

---

## Associated Resources

Add links to code, data, or other resources below. Use the format shown:

**Code repositories:**
<!-- Add GitHub/GitLab links, one per line -->


**Datasets:**
<!-- Add Zenodo/OSF/Dataverse links, one per line -->


**Other resources:**
<!-- Slides, videos, blog posts, etc. -->


---

## Notes

<!-- Any additional context, corrections, or notes -->


---

<details>
<summary>Raw metadata (for debugging)</summary>

```json
{raw_json}
```

</details>

<!-- labpubs:publication_id:{pub_id} -->"""


def get_issue_labels(
    work: Work, config: GitHubIntegrationConfig
) -> list[str]:
    """Determine labels for a verification issue.

    Args:
        work: Work to create an issue for.
        config: GitHub integration configuration.

    Returns:
        List of label strings.
    """
    labels = [config.labels.new]

    if config.author_labels:
        for author in work.authors:
            if author.name in config.author_github_map:
                slug = author.name.lower().replace(" ", "-")
                labels.append(f"author-{slug}")

    if config.year_labels and work.year:
        labels.append(str(work.year))

    return labels


def get_issue_assignees(
    work: Work, config: GitHubIntegrationConfig
) -> list[str]:
    """Determine assignees for a verification issue.

    Args:
        work: Work to create an issue for.
        config: GitHub integration configuration.

    Returns:
        List of GitHub usernames.
    """
    assignees: list[str] = []
    for author in work.authors:
        gh_user = config.author_github_map.get(author.name)
        if gh_user:
            assignees.append(gh_user)
    return assignees


def extract_publication_id(issue_body: str) -> str | None:
    """Extract the publication ID from a hidden HTML comment.

    Args:
        issue_body: Raw issue body markdown.

    Returns:
        Publication ID string or None.
    """
    match = _PUBLICATION_ID_PATTERN.search(issue_body)
    return match.group(1) if match else None


def _extract_section(
    body: str, header: str, end_header: str
) -> str:
    """Extract text between two markdown headers.

    Args:
        body: Full issue body.
        header: Start header text (e.g. "Code repositories:").
        end_header: End header text or section boundary.

    Returns:
        Section content as string.
    """
    pattern = re.compile(
        rf"\*\*{re.escape(header)}\*\*.*?\n(.*?)(?=\*\*{re.escape(end_header)}\*\*|---|\Z)",
        re.DOTALL,
    )
    match = pattern.search(body)
    return match.group(1).strip() if match else ""


def parse_issue_enrichments(issue_body: str) -> dict[str, Any]:
    """Extract structured enrichment data from a closed issue.

    Parses code repo URLs, dataset URLs, other resources, notes,
    verification checkbox status, and validity.

    Args:
        issue_body: Raw markdown body of the closed issue.

    Returns:
        Dict with keys: code_repos, datasets, other_resources,
        notes, verified, is_valid.
    """
    enrichments: dict[str, Any] = {
        "code_repos": [],
        "datasets": [],
        "other_resources": [],
        "notes": None,
        "verified": False,
        "is_valid": True,
    }

    # Parse code repositories section
    code_section = _extract_section(
        issue_body, "Code repositories:", "Datasets:"
    )
    if code_section:
        for url in _CODE_PATTERNS.findall(code_section):
            enrichments["code_repos"].append(url)

    # Parse datasets section
    dataset_section = _extract_section(
        issue_body, "Datasets:", "Other resources:"
    )
    if dataset_section:
        for url in _DATASET_PATTERNS.findall(dataset_section):
            enrichments["datasets"].append(url)

    # Parse other resources section
    other_section = _extract_section(
        issue_body, "Other resources:", "Notes"
    )
    if other_section:
        urls = re.findall(
            r"https?://[^\s)\]>]+", other_section
        )
        enrichments["other_resources"] = urls

    # Parse notes section
    notes_match = re.search(
        r"## Notes\s*\n(?:<!--.*?-->\s*\n)?(.*?)(?=---|<details|\Z)",
        issue_body,
        re.DOTALL,
    )
    if notes_match:
        notes = notes_match.group(1).strip()
        if notes:
            enrichments["notes"] = notes

    # Check verification boxes
    checklist = re.findall(
        r"- \[([ xX])\] (.+)", issue_body
    )
    for checked, text in checklist:
        if "metadata is correct" in text.lower():
            if checked.lower() == "x":
                enrichments["verified"] = True
        if "not a disambiguation error" in text.lower():
            pass
        if (
            "actually a lab publication" in text.lower()
            and checked.lower() != "x"
        ):
            enrichments["is_valid"] = False

    return enrichments


def enrichments_to_linked_resources(
    enrichments: dict[str, Any],
) -> list[LinkedResource]:
    """Convert parsed enrichments to LinkedResource objects.

    Args:
        enrichments: Dict from parse_issue_enrichments().

    Returns:
        List of LinkedResource objects.
    """
    resources: list[LinkedResource] = []
    for url in enrichments["code_repos"]:
        resources.append(
            LinkedResource(url=url, resource_type="code")
        )
    for url in enrichments["datasets"]:
        resources.append(
            LinkedResource(url=url, resource_type="dataset")
        )
    for url in enrichments["other_resources"]:
        resources.append(
            LinkedResource(url=url, resource_type="other")
        )
    return resources


def create_github_issue(
    repo: str,
    title: str,
    body: str,
    labels: list[str],
    assignees: list[str],
) -> str | None:
    """Create a GitHub issue using the gh CLI.

    Args:
        repo: Repository in "owner/repo" format.
        title: Issue title.
        body: Issue body markdown.
        labels: Labels to apply.
        assignees: GitHub usernames to assign.

    Returns:
        Issue URL or None on failure.
    """
    cmd = [
        "gh",
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        title,
        "--body",
        body,
    ]
    for label in labels:
        cmd.extend(["--label", label])
    for assignee in assignees:
        cmd.extend(["--assignee", assignee])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            logger.error(
                "gh issue create failed: %s", result.stderr
            )
            return None
        return result.stdout.strip()
    except FileNotFoundError:
        logger.error(
            "gh CLI not found. Install: https://cli.github.com"
        )
        return None
    except subprocess.TimeoutExpired:
        logger.error("gh issue create timed out")
        return None


def list_closed_issues(
    repo: str, label: str
) -> list[dict[str, Any]]:
    """List closed issues with a specific label using gh CLI.

    Args:
        repo: Repository in "owner/repo" format.
        label: Label to filter by.

    Returns:
        List of issue dicts with number, title, body, url,
        closedBy fields.
    """
    cmd = [
        "gh",
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "closed",
        "--label",
        label,
        "--json",
        "number,title,body,url,closedBy",
        "--limit",
        "100",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            logger.error(
                "gh issue list failed: %s", result.stderr
            )
            return []
        issues: list[dict[str, Any]] = orjson.loads(result.stdout)
        return issues
    except FileNotFoundError:
        logger.error(
            "gh CLI not found. Install: https://cli.github.com"
        )
        return []
    except subprocess.TimeoutExpired:
        logger.error("gh issue list timed out")
        return []


def add_issue_labels(
    repo: str, issue_number: int, labels: list[str]
) -> bool:
    """Add labels to an existing GitHub issue.

    Args:
        repo: Repository in "owner/repo" format.
        issue_number: Issue number.
        labels: Labels to add.

    Returns:
        True on success.
    """
    cmd = [
        "gh",
        "issue",
        "edit",
        str(issue_number),
        "--repo",
        repo,
    ]
    for label in labels:
        cmd.extend(["--add-label", label])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            logger.error(
                "gh issue edit failed: %s", result.stderr
            )
            return False
        return True
    except FileNotFoundError:
        logger.error(
            "gh CLI not found. Install: https://cli.github.com"
        )
        return False
    except subprocess.TimeoutExpired:
        logger.error("gh issue edit timed out")
        return False
