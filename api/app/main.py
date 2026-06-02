"""
FastAPI RL Trading Agent API.

Endpoints:
  - GET  /health   : statut + load time agent
  - GET  /version  : versions API + agent + algo
  - POST /predict  : rejoue un episode complet
  - GET  /metrics  : compteurs internes
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .rl_service import rl_service
from .schemas import (HealthResponse, MetricsResponse, PredictRequest,
                      PredictResponse, VersionResponse)
from .telemetry import (get_summary, init_telemetry, record_episode, record_error)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_telemetry()
    try:
        rl_service.load()
    except Exception as exc:
        logging.getLogger("rl-api").error("Failed to load agent: %s", exc)
    yield


app = FastAPI(title=settings.api_title, version=settings.api_version, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health():
    loaded = rl_service.agent is not None
    return HealthResponse(status="ok" if loaded else "ko",
                          agent_loaded=loaded, load_time_ms=rl_service.load_time_ms)


@app.get("/version", response_model=VersionResponse, tags=["meta"])
def version():
    return VersionResponse(api_version=settings.api_version,
                           agent_version=settings.model_version,
                           algo=rl_service.algo, framework=settings.framework)


@app.get("/metrics", response_model=MetricsResponse, tags=["meta"])
def metrics_endpoint():
    return MetricsResponse(**get_summary())


@app.post("/predict", response_model=PredictResponse, tags=["rl"])
def predict(payload: PredictRequest):
    if rl_service.agent is None:
        record_error("agent_not_loaded")
        raise HTTPException(status_code=503, detail="Agent not loaded")
    try:
        rows = [r.model_dump() for r in payload.rows]
        result, duration_ms = rl_service.run_episode(rows, payload.initial_cash)
    except ValueError as exc:
        record_error("ValueError")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        record_error(type(exc).__name__)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    record_episode(result["total_reward"], result["sharpe_ratio"], duration_ms,
                   result["n_steps"], result["n_buy"], result["n_hold"], result["n_sell"])

    return PredictResponse(
        **result,
        agent_version=settings.model_version,
        algo=rl_service.algo,
        duration_ms=round(duration_ms, 2),
    )
