"""Business logic service for orchestrating route requests."""

from typing import Any, Dict, Optional
from app.models.request import NavigationRequest, RouteRequest
from app.models.response import NavigationState, RouteResponse
from app.routing.base import RouteProvider
from app.routing.provider import DefaultRouteProvider
from app.services.navigation_service import NavigationService


class RouteService:
    """Service class encapsulating route operations and provider orchestration."""

    def __init__(
        self,
        provider: RouteProvider,
        navigation_service: Optional[NavigationService] = None,
    ) -> None:
        """Initialize RouteService with an injected RouteProvider and NavigationService.

        Args:
            provider: Concrete implementation of RouteProvider.
            navigation_service: Optional concrete instance of NavigationService.
        """
        self._provider = provider
        self._navigation_service = navigation_service or NavigationService()

    @property
    def provider(self) -> RouteProvider:
        """Get the active route provider instance."""
        return self._provider

    @property
    def navigation_service(self) -> NavigationService:
        """Get the active navigation service instance."""
        return self._navigation_service

    def calculate_route(self, request: RouteRequest) -> RouteResponse:
        """Calculate route using the underlying route provider."""
        return self._provider.calculate_route(request)

    def calculate_navigation_state(self, request: NavigationRequest) -> NavigationState:
        """Calculate real-time navigation state using the underlying navigation service."""
        return self._navigation_service.calculate_navigation_state(request)

    def get_service_status(self) -> Dict[str, Any]:
        """Get service and active provider metadata."""
        return {
            "service": "orca-route-engine",
            "provider": self._provider.get_provider_info(),
        }


def get_route_service() -> RouteService:
    """Dependency provider for FastAPI dependency injection."""
    provider = DefaultRouteProvider()
    navigation_service = NavigationService()
    return RouteService(provider=provider, navigation_service=navigation_service)
