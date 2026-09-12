from dataclasses import dataclass, field
from typing import Any


class DataSourceError(Exception):
    """Safe error raised by a structured data provider."""


@dataclass(frozen=True)
class DataRequirement:
    key: str
    label: str
    chapter_no: int
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StructuredEvidence:
    title: str
    text: str
    source_url: str
    provider: str
    dataset: str
    metadata: dict[str, Any] = field(default_factory=dict)
