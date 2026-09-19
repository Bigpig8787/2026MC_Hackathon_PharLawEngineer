from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["state"])


@router.get("/state")
def get_state(request: Request) -> dict:
    return request.app.state.runner.snapshot()
