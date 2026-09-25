"""PFZ adapters package."""

from typing import Optional

from app.adapters.pfz.base import IncoisPFZAdapter, PFZAdapter
from app.adapters.pfz.real import RealPFZAdapter
from app.core.config import Settings, get_settings


def get_pfz_adapter(settings: Optional[Settings] = None) -> PFZAdapter:
    """Factory function returning the configured PFZAdapter implementation."""
    cfg = settings or get_settings()
    provider_name = (cfg.PFZ_PROVIDER or "inmemory").lower().strip()

    if provider_name in ["inmemory", "incois", "default"]:
        return IncoisPFZAdapter()
    elif provider_name in ["teammate_api", "teammate", "real", "custom"]:
        return RealPFZAdapter(
            provider_name=provider_name,
            api_url=cfg.PFZ_API_URL,
            api_key=cfg.PFZ_API_KEY,
        )
    else:
        raise ValueError(
            f"Unsupported PFZ_PROVIDER: '{provider_name}'. Supported: ['inmemory', 'incois', 'teammate_api', 'teammate', 'real', 'custom']"
        )


__all__ = ["PFZAdapter", "IncoisPFZAdapter", "RealPFZAdapter", "get_pfz_adapter"]
