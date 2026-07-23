from fastapi import FastAPI
from pydantic import BaseModel

from trip_agent.guide_intelligence.api import router as guide_intelligence_router


class HealthResponse(BaseModel):
    status: str
    service: str


app = FastAPI(title="TripPilot Agent Service", version="0.1.0")
app.include_router(guide_intelligence_router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="UP", service="agent-service")
