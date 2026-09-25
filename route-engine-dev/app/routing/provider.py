"""Dynamic Multi-Candidate implementation of RouteProvider for marine routing."""

from typing import Dict, Optional
from app.models.request import RouteRequest
from app.models.response import RouteResponse
from app.routing.base import RouteProvider
from app.services.dynamic_route_service import (
    DynamicRouteService,
    get_dynamic_route_service,
)


class DefaultRouteProvider(RouteProvider):
    """Dynamic marine route provider with multi-candidate generation, environmental scoring, and constraint evaluation."""

    def __init__(
        self,
        name: str = "dynamic-marine-route-provider",
        version: str = "0.4.0",
        default_intermediate_waypoints: int = 3,
        dynamic_route_service: Optional[DynamicRouteService] = None,
    ) -> None:
        self.name = name
        self.version = version
        self.default_intermediate_waypoints = default_intermediate_waypoints
        self._dynamic_service = dynamic_route_service or DynamicRouteService(
            default_intermediate_waypoints=default_intermediate_waypoints
        )

    def calculate_route(self, request: RouteRequest) -> RouteResponse:
        """Calculate dynamic route using multi-candidate evaluation and environmental scoring."""
        return self._dynamic_service.calculate_route(request)

    def get_provider_info(self) -> Dict[str, str]:
        """Return provider identification details."""
        return {
            "name": self.name,
            "version": self.version,
            "status": "active",
            "intermediate_waypoints": str(self.default_intermediate_waypoints),
            "mode": "dynamic_multi_candidate",
        }
