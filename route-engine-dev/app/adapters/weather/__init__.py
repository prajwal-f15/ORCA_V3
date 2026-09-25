"""Weather adapters package."""

from typing import Optional

from app.adapters.weather.base import WeatherAdapter
from app.adapters.weather.mock import MockWeatherAdapter
from app.adapters.weather.real import RealWeatherAdapter
from app.core.config import Settings, get_settings


def get_weather_adapter(settings: Optional[Settings] = None) -> WeatherAdapter:
    """Factory function returning the configured WeatherAdapter implementation."""
    cfg = settings or get_settings()
    provider_name = (cfg.WEATHER_PROVIDER or cfg.WEATHER_ADAPTER or "mock").lower().strip()

    if provider_name == "mock":
        return MockWeatherAdapter()
    elif provider_name in ["imd", "wrf", "gfs", "real", "custom", "teammate"]:
        return RealWeatherAdapter(
            provider_name=provider_name,
            api_url=cfg.WEATHER_API_URL,
            api_key=cfg.WEATHER_API_KEY,
        )
    else:
        raise ValueError(
            f"Unsupported WEATHER_PROVIDER: '{provider_name}'. Supported: ['mock', 'imd', 'wrf', 'gfs', 'real', 'custom', 'teammate']"
        )


__all__ = ["WeatherAdapter", "MockWeatherAdapter", "RealWeatherAdapter", "get_weather_adapter"]
