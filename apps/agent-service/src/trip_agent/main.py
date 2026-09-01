from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from trip_agent.dialog.api import router as dialog_router
from trip_agent.dialog.extractor import build_extractor
from trip_agent.dialog.service import AgentDialogService, place_search_from_runtime
from trip_agent.dialog.store import build_store
from trip_agent.guide_intelligence.api import router as guide_intelligence_router
from trip_agent.places.api import (
    close_place_search_runtime,
    create_place_search_runtime,
)
from trip_agent.places.api import (
    router as places_router,
)
from trip_agent.routes.api import close_route_runtime, create_route_runtime
from trip_agent.routes.api import router as routes_router


class HealthResponse(BaseModel):
    status: str
    service: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Own the place, route, and dialog runtimes and close each resource once."""
    place_runtime = create_place_search_runtime()
    route_runtime = create_route_runtime()
    app.state.place_search_runtime = place_runtime
    app.state.route_runtime = route_runtime
    dialog_store = await build_store()
    dialog_extractor = build_extractor()
    app.state.dialog_service = AgentDialogService(
        store=dialog_store,
        extractor=dialog_extractor,
        places=place_search_from_runtime(place_runtime),
    )
    try:
        yield
    finally:
        if dialog_extractor is not None:
            await dialog_extractor.aclose()
        await dialog_store.close()
        await close_route_runtime(route_runtime)
        await close_place_search_runtime(place_runtime)


app = FastAPI(title="TripPilot Agent Service", version="0.1.0", lifespan=lifespan)
app.include_router(guide_intelligence_router)
app.include_router(places_router)
app.include_router(routes_router)
app.include_router(dialog_router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="UP", service="agent-service")
