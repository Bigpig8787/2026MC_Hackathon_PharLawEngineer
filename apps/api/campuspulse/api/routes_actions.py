from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.post("/{action_id}/confirm")
def confirm(request: Request, action_id: str) -> dict:
    runner = request.app.state.runner
    try:
        action = runner.loop.confirm_action(action_id, runner.loop.clock)
    except KeyError:
        raise HTTPException(status_code=404, detail="action not found")
    return {"action": action.model_dump(mode="json"), "state": runner.snapshot()}


@router.post("/{action_id}/reject")
def reject(request: Request, action_id: str) -> dict:
    runner = request.app.state.runner
    try:
        action = runner.loop.reject_action(action_id, runner.loop.clock)
    except KeyError:
        raise HTTPException(status_code=404, detail="action not found")
    return {"action": action.model_dump(mode="json"), "state": runner.snapshot()}
