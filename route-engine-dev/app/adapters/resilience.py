"""Resilience, retry policies, validation, caching, and timeout handling for external adapters."""

from datetime import datetime, timezone
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

from app.core.config import Settings, get_settings
from app.models.marine_conditions import OceanConditions, WeatherConditions
from app.models.pfz import PFZObservation, PFZZone
from app.models.provider import (
    FreshnessStatus,
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderError,
    ProviderErrorCategory,
    ProviderInvalidResponseError,
    ProviderNetworkError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def sanitize_message_for_logging(message: str) -> str:
    """Strip any accidental credential patterns from log strings."""
    # Basic token/key sanitization
    import re
    sanitized = re.sub(r"(api[_-]?key|token|secret|password|bearer)=([^\s&]+)", r"\1=***", message, flags=re.IGNORECASE)
    return sanitized


def execute_with_resilience(
    func: Callable[[], T],
    provider_name: str,
    max_retries: Optional[int] = None,
    retry_delay: Optional[float] = None,
    backoff_factor: Optional[float] = None,
    timeout_seconds: Optional[float] = None,
    settings: Optional[Settings] = None,
) -> T:
    """Execute a provider invocation with configurable timeout, retry logic, and error categorization.

    Retry Policy:
    - Transient errors (ProviderTimeoutError, ProviderNetworkError, ProviderUnavailableError, ProviderRateLimitError) are retried up to max_retries with exponential backoff.
    - Permanent errors (ProviderNotConfiguredError, ProviderAuthenticationError, ProviderInvalidResponseError, ValueError) fail immediately without retrying.

    Args:
        func: Zero-arg callable performing the provider request.
        provider_name: Identifier of the external provider.
        max_retries: Maximum retry attempts (default from settings).
        retry_delay: Initial retry delay in seconds.
        backoff_factor: Multiplier for backoff (e.g. 2.0).
        timeout_seconds: Timeout per attempt.
        settings: Application settings instance.

    Returns:
        Result of func().

    Raises:
        ProviderError or sub-exceptions categorized appropriately.
    """
    cfg = settings or get_settings()
    retries = max_retries if max_retries is not None else cfg.PROVIDER_MAX_RETRIES
    delay = retry_delay if retry_delay is not None else cfg.PROVIDER_RETRY_DELAY_SECONDS
    backoff = backoff_factor if backoff_factor is not None else cfg.PROVIDER_RETRY_BACKOFF_FACTOR
    timeout = timeout_seconds if timeout_seconds is not None else cfg.PROVIDER_TIMEOUT_SECONDS

    attempts = 0
    last_error: Optional[Exception] = None

    while attempts <= retries:
        attempts += 1
        try:
            logger.debug(
                "Executing request to provider '%s' (attempt %d/%d, timeout=%.1fs)",
                provider_name,
                attempts,
                retries + 1,
                timeout,
            )
            return func()

        except ProviderNotConfiguredError as exc:
            # Permanent: do not retry
            logger.warning("Provider '%s' not configured: %s", provider_name, exc)
            raise exc

        except ProviderAuthenticationError as exc:
            # Permanent: do not retry
            logger.error("Authentication failed for provider '%s': %s", provider_name, sanitize_message_for_logging(str(exc)))
            raise exc

        except ProviderInvalidResponseError as exc:
            # Permanent: malformed data cannot be fixed by retrying
            logger.error("Invalid response received from provider '%s': %s", provider_name, exc)
            raise exc

        except (ProviderTimeoutError, TimeoutError) as exc:
            last_error = ProviderTimeoutError(
                f"Request to provider '{provider_name}' timed out after {timeout:.1f}s",
                provider=provider_name,
            )
            logger.warning(
                "Timeout on attempt %d/%d for provider '%s': %s",
                attempts,
                retries + 1,
                provider_name,
                last_error,
            )

        except ProviderRateLimitError as exc:
            last_error = exc
            wait_time = exc.retry_after_seconds or delay
            logger.warning(
                "Rate limit hit for provider '%s' (attempt %d/%d). Retry-after: %.1fs",
                provider_name,
                attempts,
                retries + 1,
                wait_time,
            )
            if attempts <= retries and wait_time <= 5.0:
                time.sleep(wait_time)
                continue
            else:
                raise exc

        except (ProviderNetworkError, ProviderConnectionError, ConnectionError) as exc:
            last_error = ProviderNetworkError(
                f"Network connection failed for provider '{provider_name}': {exc}",
                provider=provider_name,
            )
            logger.warning(
                "Network failure on attempt %d/%d for provider '%s': %s",
                attempts,
                retries + 1,
                provider_name,
                exc,
            )

        except Exception as exc:
            # Unexpected exception
            last_error = ProviderError(
                f"Unexpected error calling provider '{provider_name}': {exc}",
                provider=provider_name,
            )
            logger.error("Unexpected error for provider '%s': %s", provider_name, exc, exc_info=True)
            raise last_error

        # If retries remain for transient error, sleep with backoff
        if attempts <= retries:
            sleep_duration = delay * (backoff ** (attempts - 1))
            logger.info("Retrying provider '%s' in %.2fs (attempt %d)...", provider_name, sleep_duration, attempts + 1)
            time.sleep(sleep_duration)

    # Exhausted retries
    if last_error:
        raise last_error
    raise ProviderUnavailableError(f"Provider '{provider_name}' unavailable after {attempts} attempts", provider=provider_name)


class ResponseValidator:
    """Validates raw external API dictionaries before constructing domain entities."""

    @staticmethod
    def validate_ocean_payload(data: Dict[str, Any], provider_name: str = "external_ocean") -> Dict[str, Any]:
        """Validate raw oceanographic payload against geographic and physical bounds."""
        if not isinstance(data, dict):
            raise ProviderInvalidResponseError(f"Expected dictionary payload from '{provider_name}', got {type(data)}", provider=provider_name)

        # Validate significant wave height if present
        hs = data.get("significant_wave_height_m")
        if hs is not None:
            if not isinstance(hs, (int, float)) or hs < 0.0 or hs > 35.0:
                raise ProviderInvalidResponseError(
                    f"Invalid significant_wave_height_m: {hs} (must be float 0.0-35.0m)",
                    provider=provider_name,
                )

        # Validate current speed if present
        curr_spd = data.get("current_speed_knots")
        if curr_spd is not None:
            if not isinstance(curr_spd, (int, float)) or curr_spd < 0.0 or curr_spd > 25.0:
                raise ProviderInvalidResponseError(
                    f"Invalid current_speed_knots: {curr_spd} (must be float 0.0-25.0 kts)",
                    provider=provider_name,
                )

        # Validate current direction if present
        curr_dir = data.get("current_direction_degrees")
        if curr_dir is not None:
            if not isinstance(curr_dir, (int, float)) or curr_dir < 0.0 or curr_dir >= 360.0:
                raise ProviderInvalidResponseError(
                    f"Invalid current_direction_degrees: {curr_dir} (must be float 0.0-359.9 deg)",
                    provider=provider_name,
                )

        # Validate confidence
        conf = data.get("confidence")
        if conf is not None:
            if not isinstance(conf, (int, float)) or conf < 0.0 or conf > 1.0:
                raise ProviderInvalidResponseError(
                    f"Invalid confidence score: {conf} (must be float 0.0-1.0)",
                    provider=provider_name,
                )

        return data

    @staticmethod
    def validate_weather_payload(data: Dict[str, Any], provider_name: str = "external_weather") -> Dict[str, Any]:
        """Validate raw weather payload against meteorological bounds."""
        if not isinstance(data, dict):
            raise ProviderInvalidResponseError(f"Expected dictionary payload from '{provider_name}', got {type(data)}", provider=provider_name)

        # Validate wind speed if present
        wind_spd = data.get("wind_speed_knots")
        if wind_spd is not None:
            if not isinstance(wind_spd, (int, float)) or wind_spd < 0.0 or wind_spd > 200.0:
                raise ProviderInvalidResponseError(
                    f"Invalid wind_speed_knots: {wind_spd} (must be float 0.0-200.0 kts)",
                    provider=provider_name,
                )

        # Validate visibility if present
        vis_km = data.get("visibility_km")
        if vis_km is not None:
            if not isinstance(vis_km, (int, float)) or vis_km < 0.0 or vis_km > 100.0:
                raise ProviderInvalidResponseError(
                    f"Invalid visibility_km: {vis_km} (must be float 0.0-100.0 km)",
                    provider=provider_name,
                )

        # Validate cloud cover if present
        cloud = data.get("cloud_cover_percent")
        if cloud is not None:
            if not isinstance(cloud, (int, float)) or cloud < 0.0 or cloud > 100.0:
                raise ProviderInvalidResponseError(
                    f"Invalid cloud_cover_percent: {cloud} (must be float 0.0-100.0 %)",
                    provider=provider_name,
                )

        return data


class ProviderCache:
    """Lightweight in-memory cache tracking query results and data freshness."""

    def __init__(self, default_ttl_seconds: int = 300) -> None:
        self.default_ttl = default_ttl_seconds
        self._cache: Dict[str, Tuple[Any, datetime]] = {}

    def _make_key(self, domain: str, lat: float, lon: float, precision: int = 2) -> str:
        r_lat = round(lat, precision)
        r_lon = round(lon, precision)
        return f"{domain}:{r_lat:.2f}:{r_lon:.2f}"

    def get(self, domain: str, lat: float, lon: float) -> Tuple[Optional[Any], FreshnessStatus]:
        """Retrieve cached entry and its FreshnessStatus."""
        key = self._make_key(domain, lat, lon)
        if key not in self._cache:
            return None, FreshnessStatus.UNAVAILABLE

        item, cached_at = self._cache[key]
        now = datetime.now(timezone.utc)
        age_seconds = (now - cached_at).total_seconds()

        if age_seconds <= self.default_ttl:
            return item, FreshnessStatus.FRESH
        else:
            return item, FreshnessStatus.STALE

    def set(self, domain: str, lat: float, lon: float, item: Any) -> None:
        """Store item with current UTC timestamp."""
        key = self._make_key(domain, lat, lon)
        self._cache[key] = (item, datetime.now(timezone.utc))

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
