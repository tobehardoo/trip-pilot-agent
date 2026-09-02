"""Internal HTTP entry for the agent dialog (Plan B + creation mode)."""

from fastapi import APIRouter, Header, HTTPException, Request, status

from trip_agent.dialog.models import ConfirmedSlotsResponse, DialogueRequest, DialogueResponse
from trip_agent.dialog.service import AgentDialogService
from trip_agent.internal_security import require_internal_token

router = APIRouter(prefix="/internal/v1", tags=["agent-dialog"])


def _service(request: Request) -> AgentDialogService:
    service: AgentDialogService | None = getattr(request.app.state, "dialog_service", None)
    if service is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "dialog service not ready")
    return service


@router.post("/agent/dialogue", response_model=DialogueResponse)
async def agent_dialogue(
    payload: DialogueRequest,
    request: Request,
    x_internal_token: str | None = Header(default=None),
) -> DialogueResponse:
    require_internal_token(x_internal_token)
    service = _service(request)
    if payload.session_id:
        # creation mode: no trip exists yet; the client-scoped session holds
        # the conversation until an itinerary is created from it.  The
        # composer's Required Context (destination + dates) rides along as
        # read-only TRIP facts so the wizard skips those slots instead of
        # re-asking what the user already filled in.
        scope_key = f"create:{payload.session_id}"
        context = payload.trip_context
    elif payload.trip_id:
        if payload.trip_context is None or not payload.trip_context.destination.strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "TRIP_CONTEXT_REQUIRED: trip destination context is required",
            )
        scope_key = f"trip:{payload.trip_id}"
        context = payload.trip_context
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "either sessionId (creation) or tripId (trip panel) is required",
        )
    return await service.handle(scope_key, context, payload)


@router.get("/agent/dialogue/confirmed/{session_id}", response_model=ConfirmedSlotsResponse)
async def agent_dialogue_confirmed(
    session_id: str,
    request: Request,
    x_internal_token: str | None = Header(default=None),
) -> ConfirmedSlotsResponse:
    require_internal_token(x_internal_token)
    service = _service(request)
    try:
        return await service.confirmed_creation(f"create:{session_id}")
    except KeyError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "dialog session not found"
        ) from None
