from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from trip_agent.guide_intelligence.api import router as guide_intelligence_router
from trip_agent.places.api import (
    close_place_search_runtime,
    create_place_search_runtime,
)
from trip_agent.places.api import (
    router as places_router,
)


class HealthResponse(BaseModel):
    status: str
    service: str


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Owns the place-search runtime: one provider, one optional HTTP
    client, closed exactly once on shutdown.  No module-level mutable
    provider state."""
    runtime = create_place_search_runtime()
    _app.state.place_search_runtime = runtime
    try:
        yield
    finally:
        await close_place_search_runtime(runtime)


app = FastAPI(title="TripPilot Agent Service", version="0.1.0", lifespan=lifespan)
app.include_router(guide_intelligence_router)
app.include_router(places_router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="UP", service="agent-service")
