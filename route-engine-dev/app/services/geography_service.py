"""Geography business logic service for India marine spatial datasets and features."""

from typing import List, Optional, Tuple, Union
from app.models.geography import (
    GeoDataset,
    GeoDatasetMetadata,
    GeoFeature,
    GeoFeatureType,
    GeoNearbyFeature,
)
from app.models.request import Coordinate
from app.repositories.geography_repository import (
    DuplicateFeatureError,
    GeographyRepository,
    get_default_geography_repository,
)
from app.services.geo_service import GeoService


class FeatureNotFoundError(Exception):
    """Raised when a requested feature_id is not found in the geography repository."""

    pass


class DatasetNotFoundError(Exception):
    """Raised when a requested dataset_id is not found in the geography repository."""

    pass


class InvalidFeatureTypeError(Exception):
    """Raised when an unknown feature_type string is supplied."""

    pass


class GeographyService:
    """Service orchestrating spatial features, datasets, and domain queries."""

    def __init__(self, repository: Optional[GeographyRepository] = None) -> None:
        """Initialize GeographyService with repository dependency.

        Args:
            repository: Underlying spatial repository. Defaults to shared SQLiteGeographyRepository.
        """
        self._repository = repository or get_default_geography_repository()

    def add_feature(self, feature: GeoFeature) -> GeoFeature:
        """Add and validate a geographic feature.

        Args:
            feature: GeoFeature domain entity.

        Returns:
            Saved GeoFeature.

        Raises:
            DuplicateFeatureError: If feature_id already exists.
        """
        return self._repository.add_feature(feature)

    def get_feature(self, feature_id: str) -> GeoFeature:
        """Retrieve a single geographic feature by its ID.

        Args:
            feature_id: Unique string identifier.

        Returns:
            GeoFeature entity.

        Raises:
            FeatureNotFoundError: If feature_id does not exist.
        """
        feature = self._repository.get_feature(feature_id)
        if feature is None:
            raise FeatureNotFoundError(
                f"Geographic feature with ID '{feature_id}' was not found."
            )
        return feature

    def list_features(
        self,
        feature_type: Optional[Union[str, GeoFeatureType]] = None,
        dataset_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[GeoFeature], int]:
        """Query geographic features with optional category/dataset filter and pagination.

        Args:
            feature_type: Optional string or GeoFeatureType filter.
            dataset_id: Optional dataset_id filter.
            limit: Maximum items to return.
            offset: Number of items to skip.

        Returns:
            Tuple of (list of GeoFeature items, total count matching filter).

        Raises:
            InvalidFeatureTypeError: If feature_type string is invalid.
        """
        parsed_type: Optional[GeoFeatureType] = None
        if feature_type:
            if isinstance(feature_type, GeoFeatureType):
                parsed_type = feature_type
            else:
                try:
                    parsed_type = GeoFeatureType(str(feature_type).lower())
                except ValueError:
                    valid_types = [t.value for t in GeoFeatureType]
                    raise InvalidFeatureTypeError(
                        f"Invalid feature_type '{feature_type}'. Valid types are: {valid_types}"
                    )

        return self._repository.list_features(
            feature_type=parsed_type,
            dataset_id=dataset_id,
            limit=limit,
            offset=offset,
        )

    def get_features_by_type(
        self,
        feature_type: Union[str, GeoFeatureType],
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[GeoFeature], int]:
        """Query geographic features of a specific category type.

        Args:
            feature_type: Target GeoFeatureType or string.
            limit: Maximum items to return.
            offset: Number of items to skip.

        Returns:
            Tuple of (list of GeoFeature items, total count matching type).
        """
        return self.list_features(
            feature_type=feature_type, dataset_id=None, limit=limit, offset=offset
        )

    def delete_feature(self, feature_id: str) -> bool:
        """Delete a geographic feature by ID.

        Args:
            feature_id: Unique string identifier.

        Returns:
            True if deleted.

        Raises:
            FeatureNotFoundError: If feature_id does not exist.
        """
        deleted = self._repository.delete_feature(feature_id)
        if not deleted:
            raise FeatureNotFoundError(
                f"Geographic feature with ID '{feature_id}' was not found."
            )
        return True

    def get_ports(
        self, limit: int = 50, offset: int = 0
    ) -> Tuple[List[GeoFeature], int]:
        """Retrieve registered port features."""
        return self.list_features(
            feature_type=GeoFeatureType.PORT, limit=limit, offset=offset
        )

    def get_harbours(
        self, limit: int = 50, offset: int = 0
    ) -> Tuple[List[GeoFeature], int]:
        """Retrieve registered fishing/commercial harbour features."""
        return self.list_features(
            feature_type=GeoFeatureType.HARBOUR, limit=limit, offset=offset
        )

    def get_landing_centres(
        self, limit: int = 50, offset: int = 0
    ) -> Tuple[List[GeoFeature], int]:
        """Retrieve registered fish landing centre features."""
        return self.list_features(
            feature_type=GeoFeatureType.LANDING_CENTRE, limit=limit, offset=offset
        )

    def get_lighthouses(
        self, limit: int = 50, offset: int = 0
    ) -> Tuple[List[GeoFeature], int]:
        """Retrieve registered coastal lighthouse and beacon features."""
        return self.list_features(
            feature_type=GeoFeatureType.LIGHTHOUSE, limit=limit, offset=offset
        )

    def find_nearby_features(
        self,
        latitude: float,
        longitude: float,
        feature_type: Optional[Union[str, GeoFeatureType]] = None,
        dataset_id: Optional[str] = None,
        radius_km: float = 50.0,
        limit: int = 50,
    ) -> List[GeoNearbyFeature]:
        """Find geographic features within a given radius using authoritative Haversine calculations.

        Args:
            latitude: Origin latitude (-90 to 90).
            longitude: Origin longitude (-180 to 180).
            feature_type: Optional category filter.
            dataset_id: Optional dataset filter.
            radius_km: Search radius in kilometers (> 0).
            limit: Maximum items to return.

        Returns:
            List of GeoNearbyFeature items sorted by distance ascending.

        Raises:
            ValueError: If coordinates or radius are out of valid range.
            InvalidFeatureTypeError: If feature_type string is invalid.
        """
        if not (-90.0 <= latitude <= 90.0):
            raise ValueError(f"Latitude {latitude} out of valid range [-90.0, 90.0].")
        if not (-180.0 <= longitude <= 180.0):
            raise ValueError(f"Longitude {longitude} out of valid range [-180.0, 180.0].")
        if radius_km <= 0:
            raise ValueError(f"Radius must be greater than zero, got {radius_km}.")
        if limit <= 0:
            raise ValueError(f"Limit must be greater than zero, got {limit}.")

        parsed_type: Optional[GeoFeatureType] = None
        if feature_type:
            if isinstance(feature_type, GeoFeatureType):
                parsed_type = feature_type
            else:
                try:
                    parsed_type = GeoFeatureType(str(feature_type).lower())
                except ValueError:
                    valid_types = [t.value for t in GeoFeatureType]
                    raise InvalidFeatureTypeError(
                        f"Invalid feature_type '{feature_type}'. Valid types are: {valid_types}"
                    )

        # Retrieve all candidate features matching category/dataset (up to 10,000 for spatial scan)
        features, _ = self._repository.list_features(
            feature_type=parsed_type,
            dataset_id=dataset_id,
            limit=10000,
            offset=0,
        )

        origin = Coordinate(latitude=latitude, longitude=longitude)
        nearby_list: List[GeoNearbyFeature] = []

        for feat in features:
            lat = feat.latitude
            lon = feat.longitude
            if lat is None or lon is None:
                continue

            dest = Coordinate(latitude=lat, longitude=lon)
            dist_km = GeoService.haversine_distance_km(origin, dest)

            if dist_km <= radius_km:
                dist_nm = GeoService.km_to_nautical_miles(dist_km)
                bearing = GeoService.initial_bearing_degrees(origin, dest)
                nearby_list.append(
                    GeoNearbyFeature(
                        feature=feat,
                        distance_km=dist_km,
                        distance_nm=dist_nm,
                        bearing_degrees=bearing,
                    )
                )

        # Sort strictly by distance in ascending order (nearest first)
        nearby_list.sort(key=lambda item: item.distance_km)
        return nearby_list[:limit]

    def register_dataset(self, dataset: GeoDataset) -> GeoDataset:
        """Register or update a geographic dataset descriptor.

        Args:
            dataset: GeoDataset entity.

        Returns:
            Registered GeoDataset.
        """
        return self._repository.register_dataset(dataset)

    def get_dataset(self, dataset_id: str) -> GeoDataset:
        """Retrieve a specific dataset entity by ID.

        Args:
            dataset_id: Unique dataset identifier.

        Returns:
            GeoDataset domain model.

        Raises:
            DatasetNotFoundError: If dataset_id does not exist.
        """
        dataset = self._repository.get_dataset(dataset_id)
        if dataset is None:
            raise DatasetNotFoundError(
                f"Geographic dataset with ID '{dataset_id}' was not found."
            )
        return dataset

    def get_datasets(
        self, dataset_id: Optional[str] = None
    ) -> List[GeoDatasetMetadata]:
        """Retrieve registered dataset metadata descriptors.

        Args:
            dataset_id: Optional dataset identifier.

        Returns:
            List of GeoDatasetMetadata descriptors.
        """
        return self._repository.get_dataset_metadata(dataset_id=dataset_id)


def get_geography_service() -> GeographyService:
    """FastAPI dependency provider for GeographyService."""
    return GeographyService(repository=get_default_geography_repository())

