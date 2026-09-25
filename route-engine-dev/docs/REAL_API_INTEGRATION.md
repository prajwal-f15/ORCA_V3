# Real API Integration & Adapter Contract Specification

This document defines the frozen data contracts, adapter boundaries, and integration protocols required to transition the ORCA V3 Route Engine from mock testing mode to live external/team APIs.

---

## 1. Frozen Internal Data Contracts

The ORCA V3 Route Engine and Safety Governor operate exclusively against normalized internal Pydantic domain models. Core routing logic, optimization algorithms, and safety audits never depend directly on vendor-specific payloads.

### Architectural Flow

```
External API (INCOIS / IMD / PFZ / Teammate)
              ↓
   Provider Adapter Layer
              ↓
  Normalized ORCA Data Models
              ↓
   Route Optimization & Scoring
              ↓
   Authoritative Safety Governor
              ↓
      Final Route Response
```

### Core Domain Models

| Model Name | Module Location | Primary Role |
| :--- | :--- | :--- |
| `OceanConditions` | `app.models.marine_conditions` | Surface currents (speed, dir), significant wave height ($H_s$), wave period, SST |
| `WeatherConditions` | `app.models.marine_conditions` | Wind speed/direction, wind gusts, atmospheric visibility, temperature, pressure |
| `MarineConditionsSnapshot` | `app.models.marine_conditions` | Unified point/segment snapshot combining Ocean + Weather with timestamp and source |
| `PFZZone` | `app.models.pfz` | GeoJSON polygon/point potential fishing advisory zones, validity window, suitability |
| `PFZObservation` | `app.models.pfz` | Gridded oceanographic features (SST fronts, chlorophyll-a boundaries) |
| `RouteRequest` | `app.models.request` | Voyage origin, destination, vessel specs (speed, draft, UKC margin), objective profile |
| `RouteResponse` | `app.models.response` | Selected waypoints, distance, ETA, route score, constraints, safety evaluation |
| `SafetyEvaluationRequest` | `app.models.safety` | Standalone audit payload for candidate waypoint clearance |
| `SafetyCheckResult` | `app.models.safety` | Final verdict (`ALLOW`, `WARN`, `REJECT`, `DEGRADED`), blocking reasons, check states |

---

## 2. Oceanographic Provider Contract (`app/adapters/ocean/`)

### Adapter Base Interface
```python
class OceanAdapter(ABC):
    @property
    def provider_name(self) -> str: ...
    def get_provider_status(self) -> ProviderStatus: ...
    def get_conditions(self, latitude: float, longitude: float, timestamp: Optional[datetime] = None) -> Optional[OceanConditions]: ...
```

### Integration Requirements

* **Primary Provider Options**: `mock`, `incois_hycom`, `teammate_api`, `custom`
* **Configuration Keys**: `OCEAN_PROVIDER`, `OCEAN_API_URL`, `OCEAN_API_KEY`
* **Endpoint URL**: `PENDING PROVIDER CONTRACT`
* **Authentication Method**: `PENDING PROVIDER CONTRACT` (Bearer token / API Key header)
* **Request Parameters**:
  - `latitude`: Decimal degrees (WGS84, $-90.0$ to $+90.0$)
  - `longitude`: Decimal degrees (WGS84, $-180.0$ to $+180.0$)
  - `timestamp`: ISO-8601 UTC timestamp (e.g. `2026-09-14T12:00:00Z`)
* **Expected Response Fields & Units**:
  - Significant wave height ($H_s$): **Meters** ($\text{m}$)
  - Surface current speed: **Knots** ($\text{kts}$)
  - Surface current direction: **Degrees True** ($0^\circ - 359.9^\circ$)
  - Dominant wave period: **Seconds** ($\text{s}$)
  - Sea surface temperature: **Degrees Celsius** ($^\circ\text{C}$)
* **Rate Limits & SLA**: `PENDING PROVIDER CONTRACT`
* **Error Behavior**: On HTTP timeout or 5xx response, adapter raises `ProviderConnectionError` (never silently falls back to synthetic mock data).

---

## 3. Meteorological Provider Contract (`app/adapters/weather/`)

### Adapter Base Interface
```python
class WeatherAdapter(ABC):
    @property
    def provider_name(self) -> str: ...
    def get_provider_status(self) -> ProviderStatus: ...
    def get_conditions(self, latitude: float, longitude: float, timestamp: Optional[datetime] = None) -> Optional[WeatherConditions]: ...
```

### Integration Requirements

* **Primary Provider Options**: `mock`, `imd_wrf`, `gfs`, `teammate_api`, `custom`
* **Configuration Keys**: `WEATHER_PROVIDER`, `WEATHER_API_URL`, `WEATHER_API_KEY`
* **Endpoint URL**: `PENDING PROVIDER CONTRACT`
* **Authentication**: `PENDING PROVIDER CONTRACT`
* **Expected Response Fields & Units**:
  - Sustained wind speed: **Knots** ($\text{kts}$)
  - Peak wind gust: **Knots** ($\text{kts}$)
  - Wind direction: **Degrees True** ($0^\circ - 359.9^\circ$)
  - Horizontal visibility: **Kilometers** ($\text{km}$)
  - Mean sea-level pressure: **Hectopascals** ($\text{hPa}$)
  - Precipitation rate: **Millimeters per hour** ($\text{mm/h}$)
* **Forecast Horizon**: Minimum 24h to 72h maritime forecast support.
* **Error Behavior**: Network failures raise `ProviderConnectionError`.

---

## 4. Potential Fishing Zone (PFZ) Teammate Contract (`app/adapters/pfz/`)

### Adapter Base Interface
```python
class PFZAdapter(ABC):
    @property
    def provider_name(self) -> str: ...
    def get_provider_status(self) -> ProviderStatus: ...
    def fetch_active_zones(self) -> List[PFZZone]: ...
    def fetch_latest_observations(self) -> List[PFZObservation]: ...
    def get_feed_status(self) -> PFZStatus: ...
```

### Teammate API Requirements

* **Provider Option**: `teammate_api`
* **Configuration Keys**: `PFZ_PROVIDER`, `PFZ_API_URL`, `PFZ_API_KEY`
* **Endpoint URL**: `PENDING PROVIDER CONTRACT`
* **Required Schema Mappings**:
  - `zone_id`: Unique string identifier for the advisory polygon/line.
  - `geometry`: GeoJSON Polygon or MultiPolygon (WGS84 coordinates).
  - `valid_from` / `valid_until`: UTC timestamps defining operational validity window.
  - `suitability_score`: Normalized value ($0.0$ to $100.0$ or $0.0$ to $1.0$).
  - `confidence`: Prediction confidence score ($0.0$ to $1.0$).
  - `species_focus`: Target species or fishery category (optional).

---

## 5. Geographic & Bathymetry Data Ingestion Boundary

* **Ingestion Route**: Official administrative and hydrographic datasets enter exclusively via `app.services.geographic_ingestion_service` and `app.services.marine_constraint_service`.
* **Zero Synthetic Coordinates Rule**: No hardcoded or guessed boundary coordinates are permitted for real navigation.
* **Pending Official Feeds**:
  - Official Indian EEZ baseline coordinates (`PENDING PROVIDER CONTRACT`)
  - Official Hydrographic Office / ENC bathymetry soundings (`PENDING PROVIDER CONTRACT`)
  - Naval & maritime restricted / no-go polygon boundaries (`PENDING PROVIDER CONTRACT`)

---

## 6. Provider Selection & Status Lifecycle

The system dynamically resolves providers at startup via `app.core.config.Settings`:

| Status Enum | Description | Behavior |
| :--- | :--- | :--- |
| `AVAILABLE` | External provider configured with URL and operational | Used for live route evaluation |
| `NOT_CONFIGURED` | Real provider selected but missing URL/Key | Calling adapter raises `ProviderNotConfiguredError` |
| `MOCK` | Default local development / testing mode | Returns deterministic synthetic test data with `source="mock"` |
| `UNAVAILABLE` | External provider unreachable or endpoint down | Evaluated as `DEGRADED` by Safety Governor |
| `ERROR` | Malformed response or protocol mismatch | Raises `ProviderError` and logs diagnostics |

> [!IMPORTANT]
> **No Silent Fallback Rule**: A production real provider failure or missing configuration will **never** silently fall back to mock testing data. Missing data causes the Safety Governor to issue an explicit `DEGRADED` or `REJECT` verdict.
