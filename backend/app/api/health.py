"""Health endpoints — required for any production deployment.

GET /healthz — liveness (process is up)
GET /readyz  — readiness (LLM and dependencies reachable)
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.llm import get_llm

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readiness() -> JSONResponse:
    llm = get_llm()
    llm_ok = await llm.healthcheck()
    body = {"llm": {"provider": llm.name, "ok": llm_ok}}
    code = status.HTTP_200_OK if llm_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content=body)
