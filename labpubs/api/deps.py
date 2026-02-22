"""Shared FastAPI dependencies."""

from __future__ import annotations

import functools

from labpubs.core import LabPubs

# Populated at startup by create_app().
_config_path: str = "labpubs.yaml"


def set_config_path(path: str) -> None:
    """Override the config path used by get_engine.

    Args:
        path: Path to labpubs.yaml.
    """
    global _config_path  # noqa: PLW0603
    _config_path = path
    get_engine.cache_clear()


@functools.lru_cache(maxsize=1)
def get_engine() -> LabPubs:
    """Return a cached LabPubs engine instance.

    Returns:
        Configured LabPubs engine.

    Raises:
        FileNotFoundError: If the config file is missing.
    """
    return LabPubs(_config_path)
