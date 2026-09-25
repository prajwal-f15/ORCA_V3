"""Provider status models, freshness tracking, and exception definitions for external adapter integrations."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ProviderStatus(str, Enum):
    """Operational availability status of external/internal data feed providers."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    MOCK = "MOCK"
    ERROR = "ERROR"


class FreshnessStatus(str, Enum):
    """Data freshness classification."""

    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    MOCK = "mock"


class ProviderErrorCategory(str, Enum):
    """Standardized error categories for external provider failures."""

    NOT_CONFIGURED = "NOT_CONFIGURED"
    TIMEOUT = "TIMEOUT"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_ERROR = "NETWORK_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    UNAVAILABLE = "UNAVAILABLE"


class ProviderError(Exception):
    """Base exception for all adapter and external provider integration errors."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        category: ProviderErrorCategory = ProviderErrorCategory.PROVIDER_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.category = category
        self.details = details or {}


class ProviderNotConfiguredError(ProviderError):
    """Raised when a live/real provider is selected but lacks mandatory API endpoints or credentials."""

    def __init__(self, message: str, provider: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, provider=provider, category=ProviderErrorCategory.NOT_CONFIGURED, details=details)


class ProviderTimeoutError(ProviderError):
    """Raised when a request to an external provider times out (connection or read timeout)."""

    def __init__(self, message: str, provider: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, provider=provider, category=ProviderErrorCategory.TIMEOUT, details=details)


class ProviderAuthenticationError(ProviderError):
    """Raised when authentication against external provider fails (401/403). Non-retryable."""

    def __init__(self, message: str, provider: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, provider=provider, category=ProviderErrorCategory.AUTHENTICATION_ERROR, details=details)


class ProviderRateLimitError(ProviderError):
    """Raised when external provider returns HTTP 429 Too Many Requests."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        retry_after_seconds: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        det = details or {}
        if retry_after_seconds is not None:
            det["retry_after_seconds"] = retry_after_seconds
        super().__init__(message=message, provider=provider, category=ProviderErrorCategory.RATE_LIMITED, details=det)
        self.retry_after_seconds = retry_after_seconds


class ProviderNetworkError(ProviderError):
    """Raised when network transport or connection fails."""

    def __init__(self, message: str, provider: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, provider=provider, category=ProviderErrorCategory.NETWORK_ERROR, details=details)


class ProviderConnectionError(ProviderNetworkError):
    """Raised when an external provider service is unreachable."""

    pass


class ProviderInvalidResponseError(ProviderError):
    """Raised when external provider response fails schema validation, ranges, or contains malformed data."""

    def __init__(self, message: str, provider: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, provider=provider, category=ProviderErrorCategory.INVALID_RESPONSE, details=details)


class ProviderUnavailableError(ProviderError):
    """Raised when provider returns HTTP 503 or announces service downtime."""

    def __init__(self, message: str, provider: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, provider=provider, category=ProviderErrorCategory.UNAVAILABLE, details=details)


class ProviderHealthInfo(BaseModel):
    """Diagnostic health and status information for a data provider adapter."""

    provider_name: str = Field(..., description="Unique provider or adapter identifier")
    provider_type: str = Field(..., description="Provider domain (ocean, weather, pfz, bathymetry)")
    status: ProviderStatus = Field(..., description="Current operational status")
    is_mock: bool = Field(default=False, description="Whether the provider generates synthetic/testing data")
    endpoint_configured: bool = Field(default=False, description="Whether an external URL/endpoint is configured")
    freshness: FreshnessStatus = Field(default=FreshnessStatus.FRESH, description="Freshness assessment of cached/queried data")
    last_successful_update: Optional[datetime] = Field(default=None, description="UTC timestamp of last valid data sync")
    error_category: Optional[ProviderErrorCategory] = Field(default=None, description="Error category if provider is in ERROR state")
    message: Optional[str] = Field(default=None, description="Diagnostic status description or sanitized error details")


class SystemProvidersStatusResponse(BaseModel):
    """Aggregate provider availability and readiness status for all external integrations."""

    service: str = Field(default="orca-route-engine", description="Service identifier")
    overall_status: str = Field(..., description="Overall readiness: 'operational', 'degraded', or 'unconfigured'")
    providers: Dict[str, ProviderHealthInfo] = Field(..., description="Status breakdown per provider domain")
    timestamp: datetime = Field(..., description="UTC assessment timestamp")
