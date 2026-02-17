"""Configuration loading and validation for labpubs.

Reads a YAML config file and produces a validated LabPubsConfig object.
"""

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ResearcherConfig(BaseModel):
    """Configuration for a single researcher to track."""

    name: str
    openalex_id: str | None = None
    semantic_scholar_id: str | None = None
    orcid: str | None = None
    affiliation: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    groups: list[str] = Field(default_factory=list)


class SlackConfig(BaseModel):
    """Slack notification settings."""

    webhook_url: str
    channel: str | None = None


class EmailConfig(BaseModel):
    """Email notification settings."""

    smtp_host: str
    smtp_port: int = 587
    from_address: str
    to_addresses: list[str]


class NotificationConfig(BaseModel):
    """Notification backend settings."""

    slack: SlackConfig | None = None
    email: EmailConfig | None = None


class ExportConfig(BaseModel):
    """Export file path settings."""

    bibtex_path: str | None = None
    json_path: str | None = None


class LabConfig(BaseModel):
    """Lab metadata."""

    name: str = ""
    institution: str = ""


class GrantAliasConfig(BaseModel):
    """Named alias for a specific grant."""

    funder: str
    award_id: str


class TrackedAwardConfig(BaseModel):
    """An award to track even without existing publications."""

    funder: str
    award_id: str


class GitHubLabelsConfig(BaseModel):
    """Label names for GitHub issue integration."""

    new: str = "needs-review"
    verified: str = "verified"
    has_code: str = "has-code"
    has_data: str = "has-data"
    invalid: str = "not-lab-paper"


class GitHubIntegrationConfig(BaseModel):
    """GitHub issues integration settings."""

    enabled: bool = True
    repo: str
    author_github_map: dict[str, str] = Field(
        default_factory=dict
    )
    labels: GitHubLabelsConfig = Field(
        default_factory=GitHubLabelsConfig
    )
    year_labels: bool = True
    author_labels: bool = True


class LabPubsConfig(BaseModel):
    """Top-level labpubs configuration."""

    lab: LabConfig = Field(default_factory=LabConfig)
    openalex_email: str | None = None
    semantic_scholar_api_key: str | None = None
    database_path: str = "~/.labpubs/labpubs.db"
    researchers: list[ResearcherConfig] = Field(default_factory=list)
    sources: list[str] = Field(
        default_factory=lambda: ["openalex", "semantic_scholar", "crossref"]
    )
    notifications: NotificationConfig = Field(
        default_factory=NotificationConfig
    )
    exports: ExportConfig = Field(default_factory=ExportConfig)
    grant_aliases: dict[str, GrantAliasConfig] = Field(
        default_factory=dict
    )
    tracked_awards: list[TrackedAwardConfig] = Field(
        default_factory=list
    )
    github_integration: GitHubIntegrationConfig | None = None

    @property
    def resolved_database_path(self) -> Path:
        """Return the database path with ~ expanded."""
        return Path(self.database_path).expanduser()


def load_config(config_path: str | Path) -> LabPubsConfig:
    """Load and validate a labpubs YAML configuration file.

    Args:
        config_path: Path to the YAML config file.

    Returns:
        Validated LabPubsConfig instance.

    Raises:
        FileNotFoundError: If the config file does not exist.
        yaml.YAMLError: If the YAML is malformed.
        pydantic.ValidationError: If the config fails validation.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    config = LabPubsConfig.model_validate(raw)
    logger.info(
        "Loaded config with %d researchers from %s",
        len(config.researchers),
        path,
    )
    return config
