"""Application configuration using pydantic-settings."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for the ORCA Route Engine service."""

    PROJECT_NAME: str = "orca-route-engine"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    DEFAULT_ARRIVAL_THRESHOLD_NM: float = 0.1
    ORCA_ROUTE_DB_PATH: str = "data/orca_routes.db"
    OCEAN_ADAPTER: str = "mock"
    WEATHER_ADAPTER: str = "mock"
    OCEAN_PROVIDER: str = "mock"
    WEATHER_PROVIDER: str = "mock"
    PFZ_PROVIDER: str = "inmemory"

    # External Provider Connection Parameters (Placeholders for real APIs)
    OCEAN_API_URL: str | None = None
    OCEAN_API_KEY: str | None = None
    WEATHER_API_URL: str | None = None
    WEATHER_API_KEY: str | None = None
    PFZ_API_URL: str | None = None
    PFZ_API_KEY: str | None = None

    # Provider Timeouts, Retries, Resilience & Cache Configuration
    PROVIDER_TIMEOUT_SECONDS: float = 5.0
    PROVIDER_CONNECT_TIMEOUT_SECONDS: float = 2.0
    PROVIDER_MAX_RETRIES: int = 2
    PROVIDER_RETRY_DELAY_SECONDS: float = 0.5
    PROVIDER_RETRY_BACKOFF_FACTOR: float = 2.0
    PROVIDER_CACHE_TTL_SECONDS: int = 300
    LOG_LEVEL: str = "INFO"

    # Safety Governor Test Thresholds
    MAX_TEST_WAVE_HEIGHT_BLOCK_M: float = 4.0
    MAX_TEST_WAVE_HEIGHT_WARN_M: float = 2.5
    MAX_TEST_WIND_SPEED_BLOCK_KNOTS: float = 35.0
    MAX_TEST_WIND_SPEED_WARN_KNOTS: float = 25.0
    MIN_TEST_VISIBILITY_BLOCK_KM: float = 0.5
    MIN_TEST_VISIBILITY_WARN_KM: float = 3.0
    MIN_TEST_UKC_METERS: float = 0.5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Retrieve and cache the application settings instance."""
    return Settings()
