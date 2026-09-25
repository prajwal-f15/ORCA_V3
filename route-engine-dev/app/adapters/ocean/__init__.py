"""Ocean adapters package."""

from typing import Optional

from app.adapters.ocean.base import OceanAdapter
from app.adapters.ocean.mock import MockOceanAdapter
from app.adapters.ocean.real import RealOceanAdapter
from app.core.config import Settings, get_settings


def get_ocean_adapter(settings: Optional[Settings] = None) -> OceanAdapter:
    """Factory function returning the configured OceanAdapter implementation."""
    cfg = settings or get_settings()
    # Support both OCEAN_PROVIDER and legacy OCEAN_ADAPTER
    provider_name = (cfg.OCEAN_PROVIDER or cfg.OCEAN_ADAPTER or "mock").lower().strip()

    if provider_name == "mock":
        return MockOceanAdapter()
    elif provider_name in ["incois", "hycom", "real", "custom", "teammate"]:
        return RealOceanAdapter(
            provider_name=provider_name,
            api_url=cfg.OCEAN_API_URL,
            api_key=cfg.OCEAN_API_KEY,
        )
    else:
        raise ValueError(
            f"Unsupported OCEAN_PROVIDER: '{provider_name}'. Supported: ['mock', 'incois', 'hycom', 'real', 'custom', 'teammate']"
        )


__all__ = ["OceanAdapter", "MockOceanAdapter", "RealOceanAdapter", "get_ocean_adapter"]
