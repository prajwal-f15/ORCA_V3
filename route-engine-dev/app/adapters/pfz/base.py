"""Abstract and concrete adapters for Potential Fishing Zone (PFZ) data ingestion."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.models.pfz import PFZDatasetStatus, PFZFreshness, PFZObservation, PFZStatus, PFZZone
from app.models.provider import ProviderStatus


class PFZAdapter(ABC):
    """Abstract base adapter defining the interface for PFZ model / data feed providers."""

    @property
    def provider_name(self) -> str:
        """Name of the PFZ provider."""
        return "pfz_adapter"

    def get_provider_status(self) -> ProviderStatus:
        """Query operational availability status of the PFZ provider."""
        return ProviderStatus.AVAILABLE

    @abstractmethod
    def fetch_active_zones(self) -> List[PFZZone]:
        """Fetch active potential fishing zones from upstream data source."""
        pass

    @abstractmethod
    def fetch_latest_observations(self) -> List[PFZObservation]:
        """Fetch latest prediction observations from oceanographic model."""
        pass

    @abstractmethod
    def get_feed_status(self) -> PFZStatus:
        """Query operational availability and freshness status of the feed."""
        pass


class IncoisPFZAdapter(PFZAdapter):
    """Authoritative adapter for INCOIS (Indian National Centre for Ocean Information Services) PFZ feeds.

    Primary Source: https://incois.gov.in/geoportal/MFASPFZ/index.html
    """

    def __init__(
        self,
        source_url: str = "https://incois.gov.in/geoportal/MFASPFZ/index.html",
        model_version: str = "INCOIS-PFZ-v3",
    ) -> None:
        self.source_url = source_url
        self.model_version = model_version
        self._cached_zones: List[PFZZone] = []
        self._cached_observations: List[PFZObservation] = []
        self._last_synced_at: Optional[datetime] = None

    @property
    def provider_name(self) -> str:
        return "incois"

    def get_provider_status(self) -> ProviderStatus:
        """Evaluate status based on cached dataset presence."""
        if not self._cached_zones:
            return ProviderStatus.NOT_CONFIGURED
        return ProviderStatus.AVAILABLE

    def fetch_active_zones(self) -> List[PFZZone]:
        """Retrieve cached active PFZ advisory zones.

        Returns empty list when official dataset is pending ingestion.
        """
        return self._cached_zones

    def fetch_latest_observations(self) -> List[PFZObservation]:
        """Retrieve cached PFZ observations."""
        return self._cached_observations

    def get_feed_status(self) -> PFZStatus:
        """Check status of INCOIS PFZ feed."""
        now_utc = datetime.now(timezone.utc)
        if not self._cached_zones:
            return PFZStatus(
                source="INCOIS",
                source_url=self.source_url,
                last_updated=self._last_synced_at,
                freshness=PFZFreshness.PENDING,
                dataset_status=PFZDatasetStatus.PENDING,
                feature_count=0,
                model_version=self.model_version,
                message="PFZ advisory data: Pending official dataset ingestion from INCOIS",
            )

        # Check freshness against validity
        is_fresh = any(
            z.valid_until is None or z.valid_until > now_utc for z in self._cached_zones
        )
        freshness_val = PFZFreshness.FRESH if is_fresh else PFZFreshness.STALE

        return PFZStatus(
            source="INCOIS",
            source_url=self.source_url,
            last_updated=self._last_synced_at or now_utc,
            freshness=freshness_val,
            dataset_status=PFZDatasetStatus.AVAILABLE,
            feature_count=len(self._cached_zones),
            model_version=self.model_version,
            message=f"INCOIS PFZ active advisory: {len(self._cached_zones)} zones available",
        )

    def load_zones(self, zones: List[PFZZone]) -> int:
        """Load and cache validated PFZ zones."""
        self._cached_zones = list(zones)
        self._last_synced_at = datetime.now(timezone.utc)
        return len(self._cached_zones)

    def clear(self) -> None:
        """Clear cached data."""
        self._cached_zones.clear()
        self._cached_observations.clear()
        self._last_synced_at = None
