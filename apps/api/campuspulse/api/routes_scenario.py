from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/scenario", tags=["scenario"])


@router.post("/reset")
def reset(request: Request) -> dict:
    return request.app.state.runner.reset()


@router.post("/step")
def step(request: Request) -> dict:
    return request.app.state.runner.step()


@router.post("/inject")
def inject(request: Request, overrides: dict[str, dict[str, Any]]) -> dict:
    return request.app.state.runner.inject(overrides)
