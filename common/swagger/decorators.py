from collections.abc import Sequence
from typing import Any

from drf_spectacular.utils import extend_schema


def swagger_view(
    *,
    summary: str,
    description: str,
    tags: Sequence[str],
    **schema_options: Any,
) -> Any:
    """Document a view operation with a summary, description, and tags."""
    return extend_schema(
        summary=summary,
        description=description,
        tags=list(tags),
        **schema_options,
    )