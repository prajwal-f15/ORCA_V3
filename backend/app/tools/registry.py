from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseORCATool(ABC):
    """Abstract base class for ORCA specialized tools."""

    name: str
    description: str

    @abstractmethod
    async def execute(
        self,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute the tool with the provided parameters (stub for now)."""
        pass


# Backward compatibility alias
BaseToolStub = BaseORCATool


class MarineIntelligenceTool(BaseORCATool):
    name = "marine_intelligence"
    description = "Specialized AI model for fishing potential, marine risks, historical productivity, and suitability."

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "status": "not_implemented",
            "tool": self.name,
            "message": "Marine Intelligence model is not connected yet.",
        }


class OceanPFZTool(BaseORCATool):
    name = "ocean_pfz"
    description = "INCOIS Potential Fishing Zone (PFZ) coordinate mapping and ocean state forecasts."

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "status": "not_implemented",
            "tool": self.name,
            "message": "Ocean and PFZ analysis model is not connected yet.",
        }


class RouteEngineTool(BaseORCATool):
    name = "route_engine"
    description = "Navigational waypoint and safe route optimization engine."

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "status": "not_implemented",
            "tool": self.name,
            "message": "Route optimization engine is not connected yet.",
        }


class SafetyGovernorTool(BaseORCATool):
    name = "safety_governor"
    description = "Mandatory safety verification and maritime boundary governor."

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "status": "not_implemented",
            "tool": self.name,
            "message": "Safety governor engine is not connected yet.",
        }


class WeatherTool(BaseORCATool):
    name = "weather"
    description = "Marine weather reports, wind speed, wave height, and cyclone advisories."

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "status": "not_implemented",
            "tool": self.name,
            "message": "Weather provider is not connected yet.",
        }


# Aliases for backwards compatibility
MarineIntelligenceStub = MarineIntelligenceTool
OceanPFZStub = OceanPFZTool
RouteEngineStub = RouteEngineTool
SafetyGovernorStub = SafetyGovernorTool
WeatherStub = WeatherTool


# Intent to Tool mapping configuration
INTENT_TOOL_MAP: Dict[str, Optional[str]] = {
    "fishing_potential": "marine_intelligence",
    "marine_risk": "marine_intelligence",
    "historical_productivity": "marine_intelligence",
    "marine_suitability": "marine_intelligence",
    "ocean_analysis": "ocean_pfz",
    "pfz_analysis": "ocean_pfz",
    "route_optimization": "route_engine",
    "marine_safety": "safety_governor",
    "weather_information": "weather",
    "general_orca_chat": None,
    "missing_information": None,
    "unknown": None,
}


class ToolRegistry:
    """Registry managing available tool stubs and their mappings."""

    def __init__(self):
        self._tools: Dict[str, BaseORCATool] = {
            "marine_intelligence": MarineIntelligenceTool(),
            "ocean_pfz": OceanPFZTool(),
            "route_engine": RouteEngineTool(),
            "safety_governor": SafetyGovernorTool(),
            "weather": WeatherTool(),
        }

    def register_tool(self, tool: BaseORCATool) -> None:
        """Register or replace a tool implementation."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseORCATool]:
        """Retrieve a tool by name."""
        return self._tools.get(name)

    def get_tool_for_intent(self, intent: str) -> Optional[str]:
        """Get the mapped tool name for a given intent string."""
        return INTENT_TOOL_MAP.get(intent, None)


# Global singleton tool registry
tool_registry = ToolRegistry()
