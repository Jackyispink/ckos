from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class SearchProviderError(Exception):
    """Safe, credential-free search provider error."""


@dataclass(frozen=True)
class SearchRequest:
    query: str
    limit: int = 8
    include_domains: tuple[str, ...] = ()
    exclude_domains: tuple[str, ...] = ()
    start_published_date: str | None = None
    end_published_date: str | None = None
    summary_query: str | None = None


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    text: str
    published_at: str = ''
    publisher: str = ''
    highlights: tuple[str, ...] = ()
    score: float | None = None
    provider: str = ''
    provider_result_id: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)


class SearchProvider(ABC):
    name: str

    @classmethod
    def configured(cls) -> bool:
        return True

    @abstractmethod
    async def search(self, request: SearchRequest) -> list[SearchResult]:
        raise NotImplementedError
