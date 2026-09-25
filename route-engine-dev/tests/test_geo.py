"""Unit tests for geographic calculations and maritime kinematics in GeoService."""

import math
import pytest
from app.models.request import Coordinate
from app.services.geo_service import GeoService, EARTH_RADIUS_KM, KM_PER_NAUTICAL_MILE


def test_known_haversine_distance() -> None:
    """Test Haversine distance calculation against mathematically exact benchmarks."""
    # Test 1: North Pole (90, 0) to Equator (0, 0) - exactly 1/4 of Earth circumference (pi/2 * R)
    pole = Coordinate(latitude=90.0, longitude=0.0)
    equator = Coordinate(latitude=0.0, longitude=0.0)
    expected_km = (math.pi / 2.0) * EARTH_RADIUS_KM  # ~10007.5434 km
    calculated_km = GeoService.haversine_distance_km(pole, equator)
    assert math.isclose(calculated_km, expected_km, rel_tol=1e-3)

    # Test 2: Mumbai Gateway of India (18.9220, 72.8347) to Goa Panaji (15.4909, 73.8278)
    mumbai = Coordinate(latitude=18.9220, longitude=72.8347)
    goa = Coordinate(latitude=15.4909, longitude=73.8278)
    dist_km = GeoService.haversine_distance_km(mumbai, goa)
    # Expected great circle distance is approx ~394 km
    assert 390.0 < dist_km < 400.0


def test_km_to_nautical_miles_conversion() -> None:
    """Test kilometer to nautical mile conversion with 1 NM = 1.852 km standard."""
    assert GeoService.km_to_nautical_miles(0.0) == 0.0
    assert GeoService.km_to_nautical_miles(1.852) == 1.0
    assert GeoService.km_to_nautical_miles(185.2) == 100.0
    assert math.isclose(
        GeoService.km_to_nautical_miles(10.0),
        10.0 / KM_PER_NAUTICAL_MILE,
        rel_tol=1e-3,
    )


def test_eta_calculation() -> None:
    """Test ETA in minutes based on distance in NM and vessel speed in knots."""
    # 10 NM at 10 knots = 1 hour = 60 minutes
    assert GeoService.calculate_eta_minutes(distance_nm=10.0, speed_knots=10.0) == 60.0

    # 30 NM at 15 knots = 2 hours = 120 minutes
    assert GeoService.calculate_eta_minutes(distance_nm=30.0, speed_knots=15.0) == 120.0

    # 0 NM = 0 minutes
    assert GeoService.calculate_eta_minutes(distance_nm=0.0, speed_knots=10.0) == 0.0


def test_zero_distance_route() -> None:
    """Test identical start and destination coordinates return zero distance and zero ETA."""
    coord = Coordinate(latitude=13.0827, longitude=80.2707)
    dist_km, dist_nm, eta = GeoService.calculate_metrics(coord, coord, speed_knots=12.0)
    assert dist_km == 0.0
    assert dist_nm == 0.0
    assert eta == 0.0


def test_different_vessel_speeds() -> None:
    """Test that higher speeds result in proportionally shorter ETA for the same distance."""
    start = Coordinate(latitude=18.9220, longitude=72.8347)
    dest = Coordinate(latitude=15.4909, longitude=73.8278)

    _, dist_nm, eta_slow = GeoService.calculate_metrics(start, dest, speed_knots=10.0)
    _, _, eta_medium = GeoService.calculate_metrics(start, dest, speed_knots=15.0)
    _, _, eta_fast = GeoService.calculate_metrics(start, dest, speed_knots=20.0)

    assert eta_slow > eta_medium > eta_fast
    # Fast (20 knots) should take half the time of slow (10 knots)
    assert math.isclose(eta_fast, eta_slow / 2.0, rel_tol=1e-2)


def test_invalid_zero_or_negative_vessel_speed() -> None:
    """Test that zero or negative speed raises ValueError in calculation."""
    with pytest.raises(ValueError, match="must be greater than zero"):
        GeoService.calculate_eta_minutes(distance_nm=50.0, speed_knots=0.0)

    with pytest.raises(ValueError, match="must be greater than zero"):
        GeoService.calculate_eta_minutes(distance_nm=50.0, speed_knots=-10.0)
