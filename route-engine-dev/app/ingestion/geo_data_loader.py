"""Data ingestion loader for parsing, validating, and persisting official India Marine geospatial datasets."""

import argparse
from datetime import datetime, timezone
import json
import os
import sys
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel
from app.ingestion.geo_data_validator import GeoDataValidator, GeoValidationError
from app.models.geography import (
    GeoBoundingBox,
    GeoDataset,
    GeoFeature,
    GeoFeatureType,
)
from app.repositories.geography_repository import (
    GeographyRepository,
    get_default_geography_repository,
)


class IngestionResult(BaseModel):
    """Result summary of a geospatial dataset ingestion process."""

    dataset_id: str
    feature_type: str
    feature_count: int
    bounding_box: Optional[GeoBoundingBox] = None
    processed_file_path: Optional[str] = None
    success: bool
    errors: List[str] = []

    @property
    def features_ingested(self) -> int:
        """Alias for feature_count for compatibility."""
        return self.feature_count


class GeoDataLoader:
    """Service orchestrating raw geospatial data ingestion, validation, and storage."""

    def __init__(
        self,
        repository: Optional[GeographyRepository] = None,
        processed_dir: str = "data/processed",
        save_processed: bool = True,
    ) -> None:
        """Initialize GeoDataLoader with repository and output directory.

        Args:
            repository: Underlying spatial repository (defaults to SQLiteGeographyRepository).
            processed_dir: Path to directory where processed dataset metadata artifacts are saved.
            save_processed: Whether to write processed JSON summaries to processed_dir.
        """
        self._repository = repository or get_default_geography_repository()
        self._processed_dir = processed_dir
        self._save_processed = save_processed
        if self._save_processed:
            os.makedirs(self._processed_dir, exist_ok=True)

    def _infer_feature_type(
        self,
        feature_type: Optional[Union[str, GeoFeatureType]],
        default_feature_type: Optional[Union[str, GeoFeatureType]],
        dataset_id: str,
    ) -> GeoFeatureType:
        """Infer GeoFeatureType from explicit parameters or dataset_id naming."""
        ft = feature_type or default_feature_type
        if ft is not None:
            if isinstance(ft, GeoFeatureType):
                return ft
            try:
                return GeoFeatureType(str(ft).lower())
            except ValueError:
                pass

        # Infer from dataset_id
        d_lower = dataset_id.lower()
        if "coast" in d_lower:
            return GeoFeatureType.COASTLINE
        elif "eez" in d_lower:
            return GeoFeatureType.EEZ
        elif "port" in d_lower:
            return GeoFeatureType.PORT
        elif "harbour" in d_lower:
            return GeoFeatureType.HARBOUR
        elif "landing" in d_lower:
            return GeoFeatureType.LANDING_CENTRE
        elif "light" in d_lower:
            return GeoFeatureType.LIGHTHOUSE
        elif "bathy" in d_lower:
            return GeoFeatureType.BATHYMETRY
        return GeoFeatureType.MARINE_AREA

    def ingest_file(
        self,
        file_path: str,
        dataset_id: str,
        feature_type: Optional[Union[str, GeoFeatureType]] = None,
        dataset_name: Optional[str] = None,
        name: Optional[str] = None,
        source: str = "INCOIS",
        source_url: Optional[str] = "https://incois.gov.in/geoportal/MFASPFZ/index.html",
        version: str = "1.0",
        default_feature_type: Optional[Union[str, GeoFeatureType]] = None,
    ) -> IngestionResult:
        """Ingest a raw GeoJSON file from the filesystem.

        Args:
            file_path: Path to the raw GeoJSON file.
            dataset_id: Unique identifier for the dataset (e.g. 'india_coastline').
            feature_type: Optional GeoFeatureType enum or string.
            dataset_name: Optional descriptive name.
            name: Optional descriptive name (alias).
            source: Authoritative provider (default: 'INCOIS').
            source_url: Data portal URL.
            version: Version string.
            default_feature_type: Fallback feature type.

        Returns:
            IngestionResult summarizing ingestion metrics.
        """
        parsed_type = self._infer_feature_type(feature_type, default_feature_type, dataset_id)

        if not os.path.exists(file_path):
            return IngestionResult(
                dataset_id=dataset_id,
                feature_type=parsed_type.value,
                feature_count=0,
                success=False,
                errors=[f"File not found: '{file_path}'."],
            )

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_content = f.read()
        except Exception as err:
            return IngestionResult(
                dataset_id=dataset_id,
                feature_type=parsed_type.value,
                feature_count=0,
                success=False,
                errors=[f"Failed to read file '{file_path}': {str(err)}"],
            )

        return self.ingest_geojson_data(
            raw_data=raw_content,
            dataset_id=dataset_id,
            feature_type=parsed_type,
            name=name or dataset_name,
            source=source,
            source_url=source_url,
            version=version,
        )

    def ingest_geojson_data(
        self,
        raw_data: Optional[Union[str, Dict[str, Any]]] = None,
        geojson_data: Optional[Union[str, Dict[str, Any]]] = None,
        dataset_id: str = "custom",
        feature_type: Optional[Union[str, GeoFeatureType]] = None,
        dataset_name: Optional[str] = None,
        name: Optional[str] = None,
        source: str = "INCOIS",
        source_url: Optional[str] = "https://incois.gov.in/geoportal/MFASPFZ/index.html",
        version: str = "1.0",
        default_feature_type: Optional[Union[str, GeoFeatureType]] = None,
    ) -> IngestionResult:
        """Parse, validate, persist, and export a GeoJSON dataset.

        Args:
            raw_data: GeoJSON dict or string.
            geojson_data: Alias for raw_data.
            dataset_id: Target dataset identifier.
            feature_type: Optional GeoFeatureType.
            dataset_name: Optional human-readable name.
            name: Optional human-readable name (alias).
            source: Source organization.
            source_url: Source URL.
            version: Version string.
            default_feature_type: Fallback feature type.

        Returns:
            IngestionResult.
        """
        payload = raw_data if raw_data is not None else geojson_data
        if payload is None:
            return IngestionResult(
                dataset_id=dataset_id,
                feature_type="unknown",
                feature_count=0,
                success=False,
                errors=["No GeoJSON data provided for ingestion."],
            )

        parsed_type = self._infer_feature_type(feature_type, default_feature_type, dataset_id)
        effective_name = name or dataset_name

        try:
            features, dataset = GeoDataValidator.validate_raw_geojson(
                raw_data=payload,
                dataset_id=dataset_id,
                feature_type=parsed_type,
                source=source,
                source_url=source_url,
                version=version,
            )
            if effective_name:
                dataset.name = effective_name
        except GeoValidationError as err:
            return IngestionResult(
                dataset_id=dataset_id,
                feature_type=parsed_type.value,
                feature_count=0,
                success=False,
                errors=[str(err)],
            )

        # Persist dataset record in repository
        self._repository.upsert_dataset(dataset)

        # Persist all validated features
        errors: List[str] = []
        persisted_count = 0
        for feat in features:
            try:
                self._repository.add_feature(feat)
                persisted_count += 1
            except Exception as err:
                errors.append(f"Feature '{feat.feature_id}': {str(err)}")

        processed_path = None
        if self._save_processed:
            # Save processed JSON catalog into data/processed/
            processed_path = os.path.join(self._processed_dir, f"{dataset_id}.json")
            processed_payload = {
                "dataset_id": dataset.dataset_id,
                "name": dataset.name,
                "feature_type": dataset.feature_type.value,
                "source": dataset.source,
                "source_url": dataset.source_url,
                "version": dataset.version,
                "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
                "feature_count": persisted_count,
                "bounding_box": dataset.bounding_box.model_dump() if dataset.bounding_box else None,
                "features": [
                    {
                        "feature_id": f.feature_id,
                        "name": f.name,
                        "feature_type": f.feature_type.value,
                        "geometry": f.geometry.model_dump(),
                        "properties": f.properties,
                    }
                    for f in features
                ],
            }
            try:
                with open(processed_path, "w", encoding="utf-8") as f:
                    json.dump(processed_payload, f, indent=2, ensure_ascii=False)
            except Exception as err:
                errors.append(f"Failed to write processed JSON artifact: {str(err)}")

        return IngestionResult(
            dataset_id=dataset.dataset_id,
            feature_type=dataset.feature_type.value,
            feature_count=persisted_count,
            bounding_box=dataset.bounding_box,
            processed_file_path=processed_path,
            success=len(errors) == 0,
            errors=errors,
        )


def main() -> None:
    """CLI entrypoint for executing geospatial data ingestion."""
    parser = argparse.ArgumentParser(
        description="ORCA V3 Route Engine — Official India Marine Geospatial Ingestion Tool"
    )
    parser.add_argument("file", help="Path to raw official GeoJSON file")
    parser.add_argument("--dataset-id", required=True, help="Unique dataset identifier (e.g. india_eez)")
    parser.add_argument(
        "--feature-type",
        required=True,
        choices=[t.value for t in GeoFeatureType],
        help="Feature category type",
    )
    parser.add_argument("--name", default=None, help="Human readable dataset title")
    parser.add_argument("--source", default="INCOIS", help="Authoritative data provider (default: INCOIS)")
    parser.add_argument(
        "--source-url",
        default="https://incois.gov.in/geoportal/MFASPFZ/index.html",
        help="Portal source URL",
    )
    parser.add_argument("--version", default="1.0", help="Dataset version identifier")

    args = parser.parse_args()

    loader = GeoDataLoader()
    print(f"[*] Starting ingestion for file: {args.file}")
    result = loader.ingest_file(
        file_path=args.file,
        dataset_id=args.dataset_id,
        feature_type=args.feature_type,
        name=args.name,
        source=args.source,
        source_url=args.source_url,
        version=args.version,
    )

    if result.success:
        print(f"[+] Successfully ingested dataset '{result.dataset_id}'.")
        print(f"    - Features persisted: {result.feature_count}")
        if result.bounding_box:
            bbox = result.bounding_box
            print(f"    - Bounding Box: Lat [{bbox.min_latitude}, {bbox.max_latitude}], Lon [{bbox.min_longitude}, {bbox.max_longitude}]")
        if result.processed_file_path:
            print(f"    - Processed metadata saved to: {result.processed_file_path}")
    else:
        print(f"[!] Ingestion failed for dataset '{result.dataset_id}':")
        for err in result.errors:
            print(f"    - Error: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
