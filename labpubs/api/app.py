"""FastAPI application factory for labpubs."""

from __future__ import annotations

from fastapi import FastAPI

from labpubs.api.routers import exports, researchers, stats, works


def create_app(config_path: str = "labpubs.yaml") -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config_path: Path to labpubs.yaml config file.

    Returns:
        Configured FastAPI instance with all routers mounted.
    """
    from labpubs.api.deps import set_config_path

    set_config_path(config_path)

    application = FastAPI(
        title="labpubs API",
        description="REST API for querying lab publications",
        version="0.1.0",
    )

    application.include_router(researchers.router)
    application.include_router(works.router)
    application.include_router(exports.router)
    application.include_router(stats.router)

    return application
