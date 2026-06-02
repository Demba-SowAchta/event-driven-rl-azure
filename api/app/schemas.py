"""Pydantic schemas - stricte input/output validation."""
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class OHLCVRow(BaseModel):
    """Une ligne de marche OHLCV."""
    Open:   float = Field(..., gt=0)
    High:   float = Field(..., gt=0)
    Low:    float = Field(..., gt=0)
    Close:  float = Field(..., gt=0)
    Volume: float = Field(..., ge=0)


class PredictRequest(BaseModel):
    rows: List[OHLCVRow] = Field(..., min_length=10, max_length=10000,
        description="Minimum 10 rows to compute technical indicators")
    initial_cash: float = Field(10000.0, gt=0)


class TrajectoryStep(BaseModel):
    t: int
    action: int            # 0=SELL, 1=HOLD, 2=BUY
    label: str             # "SELL"/"HOLD"/"BUY"
    position: int          # -1/0/1
    price: float
    equity: float
    reward: float


class PredictResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    actions: List[int]
    labels: List[str]
    rewards: List[float]
    equity_curve: List[float]
    total_reward: float
    final_equity: float
    cumulative_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    n_buy: int
    n_hold: int
    n_sell: int
    n_steps: int
    agent_version: str
    algo: str
    duration_ms: float


class HealthResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    status: str
    agent_loaded: bool
    load_time_ms: float


class VersionResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    api_version: str
    agent_version: str
    algo: str
    framework: str


class MetricsResponse(BaseModel):
    total_requests: int
    errors: int
    avg_latency_ms: float
