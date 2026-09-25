"""Geospatial data validation module for official India Marine datasets."""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional, Tuple, Union
from app.models.geography import (
    GeoBoundingBox,
    GeoDataset,
    GeoFeature,
    GeoFeatureType,
    GeoGeometry,
    GeometryType,
)


class GeoValidationError(Exception):
    """Raised when a geospatial dataset or feature violates GeoJSON or domain constraints."""

    pass


# Alias for backward/forward compatibility
GeoDataValidationError = GeoValidationError


class GeoDataValidator:
    """Validator ensuring strict GeoJSON RFC 7946 compliance and marine domain constraints."""

    @classmethod
    def validate_coordinate_pair(cls, pair: Any, path: str = "") -> Tuple[float, float]:
        """Validate a single [longitude, latitude] coordinate pair.

        Args:
            pair: Two-element sequence [lon, lat].
            path: Context path for debugging error messages.

        Returns:
            Tuple of (longitude, latitude) as floats.

        Raises:
            GeoValidationError: If coordinates are non-numeric or out of bounds.
        """
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise GeoValidationError(
                f"Expected [lon, lat] coordinate pair at {path}, got {pair}."
            )

        lon, lat = pair[0], pair[1]
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            raise GeoValidationError(
                f"Non-numeric coordinates at {path}: [{lon}, {lat}]."
            )

        if not (-180.0 <= lon <= 180.0):
            raise GeoValidationError(
                f"Longitude {lon} out of range [-180.0, 180.0] at {path}."
            )

        if not (-90.0 <= lat <= 90.0):
            raise GeoValidationError(
                f"Latitude {lat} out of range [-90.0, 90.0] at {path}."
            )

        return float(lon), float(lat)

    @classmethod
    def extract_and_validate_coordinates(
        cls, geometry_type: GeometryType, coordinates: Any
    ) -> List[Tuple[float, float]]:
        """Validate geometry coordinates structure and return flat list of all coordinate pairs.

        Args:
            geometry_type: GeometryType enum.
            coordinates: Nested coordinate structure.

        Returns:
            Flat list of (longitude, latitude) tuples for bounding box calculation.

        Raises:
            GeoValidationError: If geometry structure is invalid.
        """
        points: List[Tuple[float, float]] = []

        if geometry_type == GeometryType.POINT:
            pt = cls.validate_coordinate_pair(coordinates, "Point")
            points.append(pt)

        elif geometry_type == GeometryType.LINESTRING:
            if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
                raise GeoValidationError("LineString must contain at least two coordinate pairs.")
            for idx, pt in enumerate(coordinates):
                points.append(cls.validate_coordinate_pair(pt, f"LineString[{idx}]"))

        elif geometry_type == GeometryType.MULTIPOINT:
            if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 1:
                raise GeoValidationError("MultiPoint must contain at least one coordinate pair.")
            for idx, pt in enumerate(coordinates):
                points.append(cls.validate_coordinate_pair(pt, f"MultiPoint[{idx}]"))

        elif geometry_type == GeometryType.POLYGON:
            if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 1:
                raise GeoValidationError("Polygon must contain at least one linear ring.")
            for r_idx, ring in enumerate(coordinates):
                if not isinstance(ring, (list, tuple)) or len(ring) < 4:
                    raise GeoValidationError(
                        f"Polygon linear ring {r_idx} must have at least 4 positions according to RFC 7946."
                    )
                # Check closure
                if ring[0] != ring[-1]:
                    raise GeoValidationError(
                        f"Polygon linear ring {r_idx} is not closed: first and last coordinates must be identical."
                    )
                for pt_idx, pt in enumerate(ring):
                    points.append(
                        cls.validate_coordinate_pair(pt, f"Polygon.ring[{r_idx}][{pt_idx}]")
                    )

        elif geometry_type == GeometryType.MULTILINESTRING:
            if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 1:
                raise GeoValidationError("MultiLineString must contain at least one line.")
            for l_idx, line in enumerate(coordinates):
                if not isinstance(line, (list, tuple)) or len(line) < 2:
                    raise GeoValidationError(
                        f"MultiLineString line {l_idx} must contain at least two coordinates."
                    )
                for pt_idx, pt in enumerate(line):
                    points.append(
                        cls.validate_coordinate_pair(pt, f"MultiLineString[{l_idx}][{pt_idx}]")
                    )

        elif geometry_type == GeometryType.MULTIPOLYGON:
            if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 1:
                raise GeoValidationError("MultiPolygon must contain at least one polygon.")
            for p_idx, poly in enumerate(coordinates):
                if not isinstance(poly, (list, tuple)) or len(poly) < 1:
                    raise GeoValidationError(
                        f"MultiPolygon polygon {p_idx} must contain at least one linear ring."
                    )
                for r_idx, ring in enumerate(poly):
                    if not isinstance(ring, (list, tuple)) or len(ring) < 4:
                        raise GeoValidationError(
                            f"MultiPolygon[{p_idx}].ring[{r_idx}] must have at least 4 positions."
                        )
                    if ring[0] != ring[-1]:
                        raise GeoValidationError(
                            f"MultiPolygon[{p_idx}].ring[{r_idx}] is not closed: first and last coordinates must be identical."
                        )
                    for pt_idx, pt in enumerate(ring):
                        points.append(
                            cls.validate_coordinate_pair(
                                pt, f"MultiPolygon[{p_idx}][{r_idx}][{pt_idx}]"
                            )
                        )
        else:
            raise GeoValidationError(f"Unsupported geometry type: {geometry_type}")

        return points

    @classmethod
    def compute_bounding_box(
        cls, all_points: List[Tuple[float, float]]
    ) -> Optional[GeoBoundingBox]:
        """Calculate spatial bounding box from a collection of (longitude, latitude) points."""
        if not all_points:
            return None

        min_lon = min(pt[0] for pt in all_points)
        max_lon = max(pt[0] for pt in all_points)
        min_lat = min(pt[1] for pt in all_points)
        max_lat = max(pt[1] for pt in all_points)

        return GeoBoundingBox(
            min_latitude=round(min_lat, 6),
            min_longitude=round(min_lon, 6),
            max_latitude=round(max_lat, 6),
            max_longitude=round(max_lon, 6),
        )

    def validate_geojson(
        self,
        geojson_data: Any,
        default_feature_type: Union[str, GeoFeatureType] = GeoFeatureType.MARINE_AREA,
    ) -> Tuple[List[GeoFeature], Optional[GeoBoundingBox]]:
        """Instance method helper to validate GeoJSON data and return (features, bounding_box)."""
        ft = (
            default_feature_type
            if isinstance(default_feature_type, GeoFeatureType)
            else GeoFeatureType(str(default_feature_type).lower())
        )
        features, dataset = self.validate_raw_geojson(
            raw_data=geojson_data,
            dataset_id="temp_validation",
            feature_type=ft,
        )
        return features, dataset.bounding_box

    @classmethod
    def validate_raw_geojson(
        cls,
        raw_data: Union[str, Dict[str, Any]],
        dataset_id: str,
        feature_type: GeoFeatureType,
        source: str = "INCOIS",
        source_url: Optional[str] = None,
        version: str = "1.0",
    ) -> Tuple[List[GeoFeature], GeoDataset]:
        """Parse, validate, and convert a raw GeoJSON document into domain GeoFeature list and GeoDataset.

        Args:
            raw_data: GeoJSON dict or JSON string.
            dataset_id: Target dataset identifier.
            feature_type: GeoFeatureType category.
            source: Authoritative provider (e.g. INCOIS).
            source_url: Source portal URL.
            version: Version string.

        Returns:
            Tuple of (list of validated GeoFeature objects, GeoDataset entity).

        Raises:
            GeoValidationError: If JSON structure or geometry validation fails.
        """
        if isinstance(raw_data, str):
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError as err:
                raise GeoValidationError(f"Malformed JSON document: {err.msg}")
        elif isinstance(raw_data, dict):
            data = raw_data
        else:
            raise GeoValidationError(f"Expected GeoJSON dict or string, got {type(raw_data)}")

        if not isinstance(data, dict):
            raise GeoValidationError("Top-level GeoJSON structure must be a JSON object.")

        doc_type = data.get("type")
        if not doc_type:
            raise GeoValidationError("Missing top-level 'type' attribute in GeoJSON.")

        features_raw: List[Dict[str, Any]] = []

        if doc_type == "FeatureCollection":
            raw_features = data.get("features")
            if not isinstance(raw_features, list):
                raise GeoValidationError("FeatureCollection 'features' attribute must be an array.")
            features_raw = raw_features

        elif doc_type == "Feature":
            features_raw = [data]

        elif doc_type in [t.value for t in GeometryType]:
            # Direct geometry wrapped as single feature
            features_raw = [{"type": "Feature", "geometry": data, "properties": {}}]

        else:
            raise GeoValidationError(f"Unrecognized GeoJSON document type: '{doc_type}'.")

        validated_features: List[GeoFeature] = []
        all_dataset_points: List[Tuple[float, float]] = []

        for idx, feat_raw in enumerate(features_raw):
            if not isinstance(feat_raw, dict):
                raise GeoValidationError(f"Feature at index {idx} must be a JSON object.")

            geom_raw = feat_raw.get("geometry")
            if not geom_raw or not isinstance(geom_raw, dict):
                raise GeoValidationError(f"Feature at index {idx} is missing a valid 'geometry' object.")

            g_type_str = geom_raw.get("type")
            try:
                geom_type = GeometryType(g_type_str)
            except ValueError:
                raise GeoValidationError(
                    f"Feature at index {idx} has invalid geometry type '{g_type_str}'."
                )

            coords_raw = geom_raw.get("coordinates")
            pts = cls.extract_and_validate_coordinates(geom_type, coords_raw)
            all_dataset_points.extend(pts)

            # Determine feature ID
            props = feat_raw.get("properties") or {}
            feat_id = (
                feat_raw.get("id")
                or props.get("feature_id")
                or props.get("id")
                or props.get("code")
                or f"{dataset_id}_{idx + 1}"
            )
            feat_name = (
                props.get("name")
                or props.get("NAME")
                or props.get("title")
                or props.get("feature_name")
            )

            # Determine feature type (support per-feature override in properties)
            feat_ft = feature_type
            if props.get("feature_type"):
                try:
                    feat_ft = GeoFeatureType(str(props.get("feature_type")).lower())
                except ValueError:
                    pass

            geo_geom = GeoGeometry(type=geom_type, coordinates=coords_raw)

            validated_features.append(
                GeoFeature(
                    feature_id=str(feat_id),
                    dataset_id=dataset_id,
                    feature_type=feat_ft,
                    name=str(feat_name) if feat_name is not None else None,
                    geometry_type=geom_type.value,
                    geometry=geo_geom,
                    properties=props,
                    source=source,
                    source_updated_at=datetime.now(timezone.utc),
                )
            )

        bbox = cls.compute_bounding_box(all_dataset_points)
        now_utc = datetime.now(timezone.utc)

        dataset = GeoDataset(
            dataset_id=dataset_id,
            name=data.get("name") or f"India {feature_type.value.replace('_', ' ').title()}",
            feature_type=feature_type,
            source=source,
            source_url=source_url,
            version=version,
            updated_at=now_utc,
            feature_count=len(validated_features),
            bounding_box=bbox,
        )

        return validated_features, dataset
