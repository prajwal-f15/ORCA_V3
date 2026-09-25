"""Abstract base class interface for route calculation providers."""

from abc import ABC, abstractmethod
from typing import Dict
from app.models.request import RouteRequest
from app.models.response import RouteResponse


class RouteProvider(ABC):
    """Abstract interface for all route calculation providers.

    Any concrete routing engine (e.g., A*, Dijkstra, Maritime Graph, or OSRM)
    must implement this interface.
    """

    @abstractmethod
    def calculate_route(self, request: RouteRequest) -> RouteResponse:
        """Calculate a route based on validated RouteRequest input.

        Args:
            request: Validated RouteRequest containing origin, destination, vessel, and objective.

        Returns:
            RouteResponse containing computed route metadata, summary, waypoints, and constraints.
        """
        pass

    @abstractmethod
    def get_provider_info(self) -> Dict[str, str]:
        """Return metadata about the active routing provider implementation."""
        pass
