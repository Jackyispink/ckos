import os

from .base import SearchProvider, SearchProviderError
from .exa import ExaSearchProvider


_PROVIDERS: dict[str, type[SearchProvider]] = {'exa': ExaSearchProvider}


def register(name: str, provider: type[SearchProvider]):
    """Extension point for another vendor adapter."""
    _PROVIDERS[name.strip().lower()] = provider


def provider_name():
    return (os.getenv('WEB_SEARCH_PROVIDER', '') or 'exa').strip().lower()


def configured():
    name = provider_name()
    provider = _PROVIDERS.get(name)
    return bool(provider and provider.configured())


def get_provider() -> SearchProvider:
    name = provider_name()
    provider = _PROVIDERS.get(name)
    if not provider:
        available = '、'.join(sorted(_PROVIDERS))
        raise SearchProviderError(f'不支持的网页搜索厂商“{name}”；当前可用：{available}。')
    return provider()
