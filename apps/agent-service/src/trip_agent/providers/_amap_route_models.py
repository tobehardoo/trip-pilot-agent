"""Private wire and cache models for the AMap walking-route adapter."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from trip_agent.providers._route_contracts import RoutePlan
from trip_agent.providers.map import ProviderModel


class AmapCost(BaseModel):
    model_config = ConfigDict(extra="ignore")

    duration: str


class AmapWalkingStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    instruction: str
    step_distance: str
    cost: AmapCost
    polyline: str


class AmapWalkingPath(BaseModel):
    model_config = ConfigDict(extra="ignore")

    distance: str
    cost: AmapCost
    steps: tuple[AmapWalkingStep, ...]


class AmapRoute(BaseModel):
    model_config = ConfigDict(extra="ignore")

    origin: str
    destination: str
    paths: tuple[AmapWalkingPath, ...]


class AmapWalkingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    info: str
    infocode: str
    count: str = "0"
    route: AmapRoute | None = None


class CachedRoute(ProviderModel):
    data: RoutePlan
    fetched_at: datetime
