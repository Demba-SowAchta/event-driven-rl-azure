"""
RL Trading Agent - FastAPI entrypoint.

4 endpoints attendus par le sujet:
  GET  /health    sonde liveness (utilise par Container Apps)
  GET  /version   versions API + agent + framework
  POST /predict   rollout d'un episode RL sur un OHLCV
  GET  /metrics   compteurs custom (requetes, erreurs, latence moyenne)

Architecture
------------
On charge le modele via le hook `lifespan` de FastAPI (cf. PEP-563).
Avant 0.95 il fallait @app.on_event("startup") mais c'est deprecie.

Le modele reste en RAM tout le long de la vie du worker uvicorn.
On utilise UN seul worker car Container Apps scale par replicas, pas par
workers - sinon le modele serait charge N fois inutilement.

Pourquoi pas charger le modele dans /predict ?
  ~200ms a chaque appel + I/O disque + cold cache numpy.
  Pour 1000 requetes ca fait 200s de latence cumulee inutile.
"""
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .rl_service import rl_service
from .schemas import (
    HealthResponse, MetricsResponse,
    PredictRequest, PredictResponse,
    VersionResponse,
)
from .telemetry import (
    get_summary, init_telemetry,
    record_episode, record_error,
)

logger = logging.getLogger("rl-api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup:
      1. init_telemetry() configure Azure Monitor si la conn string existe
      2. rl_service.load() charge le pickle joblib en RAM
    Si load() echoue (fichier manquant, version torch incompatible) on log
    mais on ne crash pas - /health reportera status=ko, Container Apps
    marquera la revision unhealthy et fera fallback.
    """
    init_telemetry()
    try:
        rl_service.load()
        logger.info("Agent loaded in %.1fms", rl_service.load_time_ms)
    except Exception as exc:
        logger.error("Failed to load agent: %s", exc)
    yield


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    lifespan=lifespan,
    description="Reinforcement Learning trading agent. POST OHLCV bars to /predict to get a backtest.",
)

# CORS large car l'API est consommee par:
#   - le dashboard Static Web Apps (origine differente)
#   - les workers Azure Functions (egalement origine differente)
#   - les tests locaux depuis localhost
# Comme il n'y a aucun side-effect (read-only inference), c'est sans risque.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health():
    """
    Sonde liveness. Container Apps poll toutes les 30s par defaut.
    Si on retourne non-200 plusieurs fois de suite, traffic re-route.
    """
    loaded = rl_service.agent is not None
    return HealthResponse(
        status="ok" if loaded else "ko",
        agent_loaded=loaded,
        load_time_ms=rl_service.load_time_ms,
    )


@app.get("/version", response_model=VersionResponse, tags=["meta"])
def version():
    """
    Versions cote serveur. Utilise par les CI smoke-tests pour verifier
    que l'image deployee correspond au tag attendu.
    """
    return VersionResponse(
        api_version=settings.api_version,
        agent_version=settings.model_version,
        algo=settings.algo,
        framework=settings.framework,
    )


@app.get("/metrics", response_model=MetricsResponse, tags=["meta"])
def metrics_endpoint():
    """
    Compteurs custom maintenus en memoire par telemetry.py.
    Pour les vraies metriques, Application Insights reste la reference
    (sampling, percentiles, traces distribuees).
    """
    return MetricsResponse(**get_summary())


@app.post("/predict", response_model=PredictResponse, tags=["rl"])
def predict(payload: PredictRequest):
    """
    Endpoint principal: rejoue un episode RL complet sur les OHLCV recus.

    Sequence:
      1. Verifier que l'agent est charge (sinon 503 - Container Apps
         marquera la replica unhealthy)
      2. Convertir Pydantic -> dicts plain pour TradingEnv
      3. rl_service.run_episode() fait le rollout
      4. record_episode() pousse les metriques dans App Insights
      5. Renvoie PredictResponse - Pydantic verifie le schema en sortie

    Erreurs:
      503  - agent pas charge (rare, devrait etre detecte par /health avant)
      500  - exception dans le rollout (numpy, pandas, agent)
      422  - input invalide (auto par Pydantic, ex: Open negatif)
    """
    if rl_service.agent is None:
        record_error("agent_not_loaded")
        raise HTTPException(status_code=503, detail="Agent not loaded")

    rows_dict = [r.model_dump() for r in payload.rows]
    try:
        result = rl_service.run_episode(rows_dict, payload.initial_cash)
    except Exception as exc:
        record_error(type(exc).__name__)
        logger.exception("predict failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Push metriques custom vers Azure Monitor.
    record_episode(
        reward=result["total_reward"],
        sharpe=result["sharpe_ratio"],
        duration_ms=result["duration_ms"],
        n_steps=result["n_steps"],
        n_buy=result["n_buy"],
        n_hold=result["n_hold"],
        n_sell=result["n_sell"],
    )

    return PredictResponse(**result)
