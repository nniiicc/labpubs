"""Native JSON export for labpubs works.

Exports full Work models as JSON using Pydantic serialization.
"""

from typing import Any

from labpubs.models import Work


def works_to_json(works: list[Work]) -> list[dict[str, Any]]:
    """Export works as labpubs-native JSON dictionaries.

    Args:
        works: List of Work objects.

    Returns:
        List of JSON-serializable dictionaries.
    """
    return [w.model_dump(mode="json") for w in works]
