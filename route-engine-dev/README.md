# ORCA V3 Route Engine

The **Route Engine** is an independent, high-performance microservice within the **ORCA V3** AI-powered marine and fishing platform. It is solely responsible for routing algorithms, waypoint navigation abstractions, and maritime path computation.

> **Note**: This service operates independently from other ORCA components (such as ORCA Brain / Qwen3-8B, Marine Intelligence, Ocean/PFZ Model, and Safety Governor).

---

## Project Structure

```text
route-engine/
│
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI entry point & OpenAPI config
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py               # API route definitions
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py               # Settings management via pydantic-settings
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── request.py              # Pydantic request models
│   │   └── response.py             # Pydantic response models
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   └── route_service.py        # Business logic & provider orchestration
│   │
│   └── routing/
│       ├── __init__.py
│       ├── base.py                 # RouteProvider abstract base class (interface)
│       └── provider.py             # RouteProvider concrete implementation
│
├── tests/
│   ├── __init__.py
│   └── test_health.py              # Pytest test suite for health & core contracts
│
├── .env                            # Environment variables
├── .gitignore                      # Git ignore rules for Python & Windows
├── requirements.txt                # Project dependencies
└── README.md                       # Documentation and usage guide
```

---

## Getting Started (Windows PowerShell)

### 1. Prerequisites
- Python **3.11+** installed and available in PATH.

### 2. Create Virtual Environment
Open PowerShell in the project directory:

```powershell
python -m venv .venv
```

### 3. Activate Virtual Environment
```powershell
.\.venv\Scripts\Activate.ps1
```

*(If PowerShell script execution is restricted, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first)*

### 4. Install Dependencies
```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Running the API

Start the development server with hot-reload enabled:

```powershell
uvicorn app.main:app --reload
```

The service will be accessible at:
- **Base URL**: `http://127.0.0.1:8000`
- **Health Check**: `http://127.0.0.1:8000/health`
- **Interactive OpenAPI Documentation (Swagger UI)**: `http://127.0.0.1:8000/docs`
- **ReDoc Documentation**: `http://127.0.0.1:8000/redoc`

---

## Running Tests

Execute the automated test suite using `pytest`:

```powershell
pytest -v
```

---

## Architecture Principles
- **Algorithm Decoupling**: The API layer and business logic depend strictly on the `RouteProvider` abstract interface (`app/routing/base.py`). Concrete routing algorithms are decoupled and pluggable without modifying endpoint contracts.
- **Type Safety**: Full type annotations across all modules validated with Pydantic v2.
- **Configuration Management**: Strict typed configuration using `pydantic-settings` loaded from `.env`.

---

## STEP 10 — REAL OFFICIAL INDIA GEO DATA

The ORCA V3 Route Engine includes a data ingestion and validation subsystem designed specifically for **authoritative Government of India / INCOIS marine geospatial datasets**.

### 1. Authoritative Data Source
- **Provider**: Indian National Centre for Ocean Information Services (INCOIS), Ministry of Earth Sciences, Govt. of India.
- **Geoportal URL**: [INCOIS MFAS/PFZ Geoportal](https://incois.gov.in/geoportal/MFASPFZ/index.html)
- **Target Layers**:
  - India Coastline / Marine Boundary (`coastline`)
  - India Exclusive Economic Zone (`eez`)
  - Marine Areas & Coastal Sectors (`marine_area`)
  - Landing Centres & Ports (`landing_centre`, `port`, `harbour`)
  - Navigational Aids & Bathymetry (`lighthouse`, `bathymetry`)

### 2. Expected Data Format
- **Standard**: RFC 7946 GeoJSON (`FeatureCollection`, `Feature`, `Polygon`, `MultiPolygon`, `LineString`, `Point`).
- **Coordinate System**: WGS 84 (`EPSG:4326`).
- **Coordinate Ordering**: Strictly `[longitude, latitude]` (e.g. `[72.8347, 18.9220]`).
- **Coordinate Bounds**:
  - Longitude: `[-180.0, 180.0]`
  - Latitude: `[-90.0, 90.0]`
- **Polygon Constraints**: Linear rings must have at least 4 coordinate pairs, and the first coordinate must match the last coordinate (closed ring).

### 3. How to Place Raw Data Files
Save official files downloaded from the INCOIS geoportal into `data/raw/`:
```text
data/
└── raw/
    ├── india_coastline.geojson
    ├── india_eez.geojson
    └── landing_centres.geojson
```

### 4. Running Ingestion
Run the ingestion CLI command with your target file:

```powershell
# Ingest India EEZ Boundary
python -m app.ingestion.geo_data_loader data/raw/india_eez.geojson --dataset-id india_eez --feature-type eez --name "Official India EEZ Boundary" --source "INCOIS" --version "2026.1"

# Ingest India Coastline
python -m app.ingestion.geo_data_loader data/raw/india_coastline.geojson --dataset-id india_coastline --feature-type coastline --name "Official India Coastline Boundary" --source "INCOIS" --version "2026.1"
```

### 5. How Validation Works
The `GeoDataValidator` enforces rigorous checks without modifying raw geometries:
1. Validates top-level GeoJSON syntax and feature structure.
2. Rejects out-of-bounds coordinates outside `[-180, 180]` lon and `[-90, 90]` lat.
3. Enforces RFC 7946 Polygon ring closure and minimum vertex counts.
4. Preserves feature properties (`props`) and extracts authoritative feature identifiers.
5. Computes bounding boxes (`min_latitude`, `max_latitude`, `min_longitude`, `max_longitude`) across all features.

### 6. Storage & Processed Artifacts
- **SQLite Database**: Persisted in tables `geo_datasets` and `geo_features` with foreign keys and indexes.
- **Processed Catalogs**: Exported to `data/processed/<dataset_id>.json` containing dataset metadata, computed bounding boxes, and feature lists.

### 7. Geography API Endpoints
- `GET /geography/datasets` — List all registered dataset descriptors and status.
- `GET /geography/datasets/{dataset_id}` — Get single dataset metadata by ID.
- `GET /geography/features` — Query features with optional `?dataset_id=<id>` or `?feature_type=<type>` and pagination (`?limit=50&offset=0`).
- `GET /geography/features/{feature_id}` — Retrieve single feature by ID.
- `GET /geography/features/type/{feature_type}` — Query features by category type.

---

## STEP 11 — PORTS / HARBOURS / LANDING CENTRES / LIGHTHOUSES

Step 11 extends the ORCA V3 geography domain to support authoritative Indian marine facilities, navigational aids, and coastal infrastructure.

### 1. Target Maritime Infrastructure Categories
- **Major & Minor Ports (`port`)**: Commercial ports across West and East coasts of India. (Authoritative Source: Ministry of Ports, Shipping and Waterways / INCOIS).
- **Fishing Harbours (`harbour`)**: Designated artisanal and mechanized fishing harbours. (Authoritative Source: INCOIS MFAS/PFZ Geoportal / Dept of Fisheries).
- **Fish Landing Centres (`landing_centre`)**: Official coastal fish landing centres. (Authoritative Source: INCOIS MFAS/PFZ Geoportal).
- **Lighthouses & Beacons (`lighthouse`)**: Aids to navigation along the Indian coastline and island territories. (Authoritative Source: Directorate General of Lighthouses and Lightships - DGLL).

### 2. Feature Schema & Property Normalization
Each marine facility feature is stored with strict `[longitude, latitude]` Point geometries and property helpers:
- `feature_id`: Unique identifier (e.g. `in_mum_port`, `in_sassoon_dock`)
- `dataset_id`: Dataset classification (`india_ports`, `india_harbours`, `india_landing_centres`, `india_lighthouses`)
- `feature_type`: Category enum (`port`, `harbour`, `landing_centre`, `lighthouse`)
- `name`: Official facility name
- `latitude` / `longitude`: Extracted decimal degree coordinates
- `state` / `district`: Administrative coastal jurisdiction
- `code`: Official code (e.g. UN/LOCODE, DGLL light number, port code)
- `properties`: Unmodified source metadata dictionary

### 3. Ingesting Point Datasets
Place downloaded official GeoJSON files into `data/raw/` and run:

```powershell
# Ingest Official Ports
python -m app.ingestion.geo_data_loader data/raw/india_ports.geojson --dataset-id india_ports --feature-type port --name "India Major & Minor Ports" --source "Ministry of Ports"

# Ingest Official Fish Landing Centres
python -m app.ingestion.geo_data_loader data/raw/landing_centres.geojson --dataset-id india_landing_centres --feature-type landing_centre --name "India Fish Landing Centres" --source "INCOIS"

# Ingest Official Lighthouses
python -m app.ingestion.geo_data_loader data/raw/lighthouses.geojson --dataset-id india_lighthouses --feature-type lighthouse --name "India Coastal Lighthouses" --source "DGLL"
```

### 4. Nearby Facilities Search API
Use geodesic distance calculations to find nearby facilities from any vessel or reference coordinate:

```http
GET /geography/nearby?latitude=18.9220&longitude=72.8347&radius_km=50&feature_type=harbour&limit=10
```

**Response Format**:
```json
{
  "origin_latitude": 18.922,
  "origin_longitude": 72.8347,
  "radius_km": 50.0,
  "total": 1,
  "features": [
    {
      "feature": {
        "feature_id": "in_sassoon_dock",
        "dataset_id": "india_harbours",
        "feature_type": "harbour",
        "name": "Sassoon Fishing Harbour",
        "geometry": {
          "type": "Point",
          "coordinates": [72.825, 18.91]
        },
        "properties": { "state": "Maharashtra", "district": "Mumbai" },
        "source": "INCOIS"
      },
      "distance_km": 1.68,
      "distance_nm": 0.91,
      "bearing_degrees": 218.4
    }
  ]
}
```

### 5. Frontend Visual Layers & Scanner
The testing console includes:
- Layer toggles for `Ports`, `Harbours`, `Landing Centres`, and `Lighthouses` with custom styled interactive markers.
- Facilities Scanner tool to scan nearby facilities around the current vessel GPS or route origin.
- Zero fake markers policy: layers display only authentic persisted records from SQLite.

---

## STEP 12 — BATHYMETRY + RESTRICTED / NO-GO AREAS

Step 12 prepares the ORCA V3 Route Engine to consume authoritative marine hydrographic depth data and restricted / no-go marine zones.

> [!IMPORTANT]
> **Strict Data Policy: REAL DATA > Fake Data**
> No synthetic bathymetry, fake soundings, or artificial restricted-area polygons have been generated or inserted.
> The complete architecture, domain models, spatial constraint services, and API endpoints are implemented and fully functional, ready to ingest real datasets from official authorities.

### 1. Authoritative Official Data Sources
- **INCOIS MFAS/PFZ Geoportal**: [https://incois.gov.in/geoportal/MFASPFZ/index.html](https://incois.gov.in/geoportal/MFASPFZ/index.html) (Bathymetric contours, Marine Protected Areas)
- **National Hydrographic Office (NHO) / Dehradun**: Official navigational charts and Notice to Mariners.
- **Ministry of Environment, Forest and Climate Change (MoEFCC)**: Marine National Parks and Sanctuary Boundaries.
- **Directorate General of Shipping / Indian Coast Guard**: Navigational safety corridors and military exercise sectors.

### 2. Status: Implemented Architecture vs Actual Official Data

| Category | Implemented Architecture | Actual Official Records Ingested | Status |
| :--- | :--- | :--- | :--- |
| **Bathymetry / Sea Depth** | Domain models, depth property normalization (`depth_meters`, `minimum_depth_meters`, `maximum_depth_meters`), point soundings, polygon depth zones, Haversine proximity search, draft clearance checks | 0 records | **Pending Official Dataset** |
| **Restricted / No-Go Areas** | Polygon & MultiPolygon ray-casting point-in-polygon, line-segment boundary intersection, multi-segment route verification, restriction type extraction | 0 records | **Pending Official Dataset** |

### 3. Data Ingestion Commands
To ingest official GeoJSON files when downloaded:

```powershell
# Ingest Official Bathymetric Contours / Soundings
python -m app.ingestion.geo_data_loader data/raw/india_bathymetry.geojson --dataset-id india_bathymetry --feature-type bathymetry --name "India Coastal Bathymetry & Depth Contours" --source "NHO / INCOIS"

# Ingest Official Marine Restricted / Protected Areas
python -m app.ingestion.geo_data_loader data/raw/india_restricted_areas.geojson --dataset-id india_restricted_areas --feature-type restricted_area --name "India Marine Protected & Restricted Navigation Areas" --source "MoEFCC / Coast Guard"
```

### 4. Marine Constraint Service (`MarineConstraintService`)
The service layer (`app/services/marine_constraint_service.py`) provides clean, decoupled safety inspection methods:

- `check_coordinate_restrictions(latitude, longitude)`: Determines if a GPS point falls within any restricted Polygon or MultiPolygon using ray-casting.
- `check_route_segment_restrictions(start_lat, start_lon, end_lat, end_lon)`: Evaluates if a navigational line segment crosses any restricted boundary ring using 2D segment intersection tests.
- `check_route_restrictions(waypoints, vessel_draft_meters)`: Scans an entire planned route sequence and returns list of crossed zones and segment warnings.
- `get_depth_at_coordinate(latitude, longitude, search_radius_km)`: Looks up depth from polygon depth zones or nearest point soundings.
- `validate_vessel_draft(latitude, longitude, vessel_draft_meters, minimum_safe_depth_meters, safety_margin_meters)`: Calculates Under-Keel Clearance ($UKC = Depth - Draft$) and returns safety status (`SAFE`, `CRITICAL_DEPTH`, `WARNING`, `UNKNOWN_DEPTH`).

### 5. API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/geography/features/type/bathymetry` | List registered bathymetric depth features |
| `GET` | `/geography/features/type/restricted_area` | List registered restricted marine area features |
| `GET` | `/geography/restrictions/check?latitude=...&longitude=...` | Test if coordinate lies inside a restricted marine zone |
| `GET` | `/geography/restrictions/nearby?latitude=...&longitude=...&radius_km=...` | Find restricted zones within search radius |
| `POST` | `/geography/restrictions/check-route` | Test full route coordinate sequence against restricted zones |
| `GET` | `/geography/depth?latitude=...&longitude=...` | Query estimated sea depth at coordinate |
| `GET` | `/geography/depth/validate-draft?latitude=...&longitude=...&draft_meters=...` | Validate vessel draft and under-keel clearance |
| `GET` | `/geography/bathymetry/nearby?latitude=...&longitude=...&radius_km=...` | Find nearest bathymetric soundings within radius |

### 6. Frontend Testing Console Layers
- **Bathymetry Layer Toggle (`🌊 Bathymetry`)**: Visualizes real depth polygons and soundings when imported; shows *"Bathymetry data: Pending official dataset"* when empty.
- **Restricted Areas Layer Toggle (`🚫 Restricted Areas`)**: Visualizes real restricted polygons with boundary details; shows *"Restricted-area data: Pending official dataset"* when empty.
- **Vessel Draft Inputs**: Optional Draft (m) and Min Safe Depth (m) fields integrated into route planning.

---

## STEP 13 — PFZ MODEL INTEGRATION FOR ORCA V3 ROUTE ENGINE

Step 13 introduces the Potential Fishing Zone (PFZ) domain, advisory adapter pipeline, and destination candidate ranking subsystem for the ORCA V3 Route Engine.

```text
PFZ Oceanographic Model / INCOIS Advisory
                  ↓
       PFZ Service / Adapter
                  ↓
       Route Engine (Candidate Targets)
                  ↓
       Deterministic Route Scoring
                  ↓
        Optimized Fishing Route
```

> [!IMPORTANT]
> **Safety Separation Principle: Fishing Potential $\neq$ Navigation Safety**
> A high PFZ score indicates fish abundance potential based on oceanographic thermal/chlorophyll fronts, NOT navigational safety.
> PFZ candidate destinations must always be routed through marine safety constraints (Bathymetry, Restricted Areas, and the future Safety Governor).

### 1. Authoritative Official Data Source
- **Primary Provider**: Indian National Centre for Ocean Information Services (INCOIS), Ministry of Earth Sciences, Govt. of India.
- **Geoportal URL**: [https://incois.gov.in/geoportal/MFASPFZ/index.html](https://incois.gov.in/geoportal/MFASPFZ/index.html)
- **Parameters Provided**: Sea Surface Temperature (SST) gradients, Chlorophyll-a fronts, targeted pelagic species (Tuna, Mackerel, Sardine), advisory validity windows.

### 2. Status: Implemented Architecture vs Actual Official Data

| Component | Implemented Architecture | Actual Official Records Ingested | Status |
| :--- | :--- | :--- | :--- |
| **PFZ Advisory Feed (`india_pfz`)** | Full domain models (`PFZZone`, `PFZObservation`), GeoJSON loader, SQLite persistence, proximity queries, deterministic destination ranking | 0 records | **Pending Official Dataset** |

### 3. PFZ Candidate Scoring Formula
The Route Engine evaluates candidate fishing zones near the vessel using a deterministic, transparent composite score ($0 \text{ to } 100$):

$$\text{RankingScore} = w_s \cdot \text{Suitability} + w_c \cdot (\text{Confidence} \times 100) + w_d \cdot \text{DistanceScore}$$

$$\text{DistanceScore} = \max\left(0,\, 100 \cdot \left(1 - \frac{d}{d_{\max}}\right)\right)$$

#### Weight Profiles by Routing Objective:
- **`balanced` (Default)**: $w_s = 0.45, w_c = 0.25, w_d = 0.30$
- **`highest_potential`**: $w_s = 0.70, w_c = 0.20, w_d = 0.10$
- **`nearest_distance`**: $w_s = 0.20, w_c = 0.10, w_d = 0.70$
- **`high_confidence`**: $w_s = 0.30, w_c = 0.60, w_d = 0.10$

### 4. Data Freshness Lifecycle
- `available`: Active advisory with current validity timestamp.
- `fresh`: Updated within the last 48 hours.
- `stale`: Advisory expired or older than 48 hours.
- `pending`: Official feed/file not yet loaded (0 records).
- `unavailable`: Data feed offline.

### 5. API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/pfz/status` | Operational availability and freshness report |
| `GET` | `/pfz/zones` | List registered PFZ zones (`?limit=50&min_confidence=0.8`) |
| `GET` | `/pfz/zones/{pfz_id}` | Retrieve single PFZ zone by unique ID |
| `GET` | `/pfz/zones/nearby?latitude=...&longitude=...&radius_km=...` | Find PFZ zones within search radius |
| `GET` | `/pfz/best?latitude=...&longitude=...&radius_km=100` | Ranked candidate destinations for Route Engine (GET) |
| `POST` | `/pfz/best` | Ranked candidate destinations for Route Engine (POST payload) |

### 6. Data Ingestion Commands
To ingest official PFZ GeoJSON files when downloaded:

```powershell
python -m app.ingestion.geo_data_loader data/raw/india_pfz.geojson --dataset-id india_pfz --feature-type pfz --name "India Potential Fishing Zones" --source "INCOIS"
```

---

## Step 14 — Ocean + Weather Integration

Step 14 introduces the **Oceanographic & Meteorological Integration Subsystem** for the ORCA V3 Route Engine.

```text
External Feeds (Mock / Teammate APIs)
             ↓
[OceanAdapter]     [WeatherAdapter]
             ↓             ↓
       [OceanService]   [WeatherService]
             ↘             ↙
     [MarineConditionsService] (Orchestrator)
                   ↓
   MarineConditionsSnapshot (Normalized)
                   ↓
             Route Engine
```

> [!IMPORTANT]
> **Safety Authority Principle:**
> `MarineConditionsService`, `OceanService`, and `WeatherService` are strictly aggregation and normalization pipelines. They **never** declare a navigational safety verdict (`safe=True` or `ALLOW`).
> The **Safety Governor** remains the sole, final authority for vessel navigation safety.

### 1. Key Architectural Components
- **Normalized Data Models (`app/models/marine_conditions.py`)**:
  - `OceanConditions`: surface current speed/direction, significant wave height/period/direction, sea surface temperature (SST), salinity, confidence, source metadata.
  - `WeatherConditions`: sustained wind speed/direction/gusts, air temperature, atmospheric pressure, visibility, precipitation, cloud cover, confidence.
  - `MarineConditionsSnapshot`: unified assessment containing geographic position, UTC timestamp, ocean conditions, weather conditions, status, and source summary.
- **Pluggable Adapters (`app/adapters/ocean/`, `app/adapters/weather/`)**:
  - `OceanAdapter` & `WeatherAdapter`: abstract base interfaces exposing `get_conditions(latitude, longitude, timestamp)`.
  - `MockOceanAdapter` & `MockWeatherAdapter`: deterministic mock adapters identifying `source="mock"`.
  - Factory pattern (`get_ocean_adapter()`, `get_weather_adapter()`) controlled via environment settings (`OCEAN_ADAPTER=mock`, `WEATHER_ADAPTER=mock`).
- **Service Layer (`app/services/`)**:
  - `OceanService`: consumes ocean adapter, handles exceptions cleanly, validates normalization.
  - `WeatherService`: consumes weather adapter, handles exceptions cleanly, validates normalization.
  - `MarineConditionsService`: orchestrates combined snapshot, handles partial/unavailable/mock statuses.
- **Route Engine Integration**:
  - `RouteRequest` optionally accepts `environmental_conditions`.
  - `RouteResponse` returns `marine_conditions`.
  - Fully backward-compatible when conditions are omitted or unavailable.

### 2. API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/marine/conditions?latitude=18.52&longitude=72.85` | Retrieve normalized oceanographic + weather snapshot |
| `GET` | `/api/v1/marine/conditions?latitude=18.52&longitude=72.85` | Versioned alias for marine conditions endpoint |


