"""Unit tests for deterministic waypoint generation service."""

import pytest
from app.models.request import Coordinate
from app.services.waypoint_service import WaypointGenerator


def test_zero_intermediate_waypoints() -> None:
    """Test generating 0 intermediate waypoints yields exactly [start, destination]."""
    start = Coordinate(latitude=18.5000, longitude=72.8000)
    dest = Coordinate(latitude=18.6000, longitude=72.9000)

    waypoints = WaypointGenerator.generate_linear_waypoints(start, dest, num_intermediate=0)
    assert len(waypoints) == 2
    assert waypoints[0].latitude == 18.5000
    assert waypoints[0].longitude == 72.8000
    assert waypoints[1].latitude == 18.6000
    assert waypoints[1].longitude == 72.9000


def test_one_intermediate_waypoint() -> None:
    """Test generating 1 intermediate waypoint produces midpoint."""
    start = Coordinate(latitude=10.0, longitude=20.0)
    dest = Coordinate(latitude=20.0, longitude=40.0)

    waypoints = WaypointGenerator.generate_linear_waypoints(start, dest, num_intermediate=1)
    assert len(waypoints) == 3
    # Midpoint should be (15.0, 30.0)
    assert waypoints[0].latitude == 10.0
    assert waypoints[0].longitude == 20.0
    assert waypoints[1].latitude == 15.0
    assert waypoints[1].longitude == 30.0
    assert waypoints[2].latitude == 20.0
    assert waypoints[2].longitude == 40.0


def test_multiple_intermediate_waypoints() -> None:
    """Test generating 3 intermediate waypoints creates 5 total waypoints with equal spacing."""
    start = Coordinate(latitude=18.5000, longitude=72.8000)
    dest = Coordinate(latitude=18.9000, longitude=73.2000)

    waypoints = WaypointGenerator.generate_linear_waypoints(start, dest, num_intermediate=3)
    assert len(waypoints) == 5  # start, WP1, WP2, WP3, dest

    # Check linear progression
    assert waypoints[0].latitude == 18.5000
    assert waypoints[1].latitude == 18.6000
    assert waypoints[2].latitude == 18.7000
    assert waypoints[3].latitude == 18.8000
    assert waypoints[4].latitude == 18.9000

    assert waypoints[0].longitude == 72.8000
    assert waypoints[1].longitude == 72.9000
    assert waypoints[2].longitude == 73.0000
    assert waypoints[3].longitude == 73.1000
    assert waypoints[4].longitude == 73.2000


def test_exact_start_and_destination_preserved() -> None:
    """Test that the first coordinate is strictly start and the last is strictly destination."""
    start = Coordinate(latitude=18.922012, longitude=72.834711)
    dest = Coordinate(latitude=15.490933, longitude=73.827844)

    waypoints = WaypointGenerator.generate_linear_waypoints(start, dest, num_intermediate=4)
    assert waypoints[0].latitude == round(start.latitude, 6)
    assert waypoints[0].longitude == round(start.longitude, 6)
    assert waypoints[-1].latitude == round(dest.latitude, 6)
    assert waypoints[-1].longitude == round(dest.longitude, 6)


def test_waypoint_ordering() -> None:
    """Test waypoints are strictly ordered from start to destination."""
    start = Coordinate(latitude=10.0, longitude=10.0)
    dest = Coordinate(latitude=50.0, longitude=50.0)

    waypoints = WaypointGenerator.generate_linear_waypoints(start, dest, num_intermediate=4)
    for i in range(len(waypoints) - 1):
        assert waypoints[i].latitude < waypoints[i + 1].latitude
        assert waypoints[i].longitude < waypoints[i + 1].longitude


def test_invalid_negative_waypoint_count() -> None:
    """Test ValueError is raised when num_intermediate is negative."""
    start = Coordinate(latitude=18.5000, longitude=72.8000)
    dest = Coordinate(latitude=18.6000, longitude=72.9000)

    with pytest.raises(ValueError, match="must be greater than or equal to 0"):
        WaypointGenerator.generate_linear_waypoints(start, dest, num_intermediate=-1)


def test_start_and_destination_identical() -> None:
    """Test that when start and destination are identical, all waypoints match the coordinate."""
    coord = Coordinate(latitude=18.5000, longitude=72.8000)
    waypoints = WaypointGenerator.generate_linear_waypoints(coord, coord, num_intermediate=3)
    assert len(waypoints) == 5
    for wp in waypoints:
        assert wp.latitude == 18.5000
        assert wp.longitude == 72.8000
