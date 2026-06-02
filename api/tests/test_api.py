"""
Tests unitaires pytest pour l'API RL Trading Agent.

Couvre les 3 cas exiges + 7 cas bonus:
  1. Succes      : episode complet 50 jours, verifie schema
  2. Input invalide : Open negatif (Field gt=0)
  3. Payload manquant : champ Volume absent
  4. Trop court (< 10 rows) : 400 Bad Request
  5. Healthcheck, version, metrics
  6. Cumulative return est bien (final - initial) / initial
  7. Sharpe est un float fini
  8. n_buy + n_hold + n_sell == n_steps
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["MODEL_PATH"] = str(
    Path(__file__).resolve().parents[2] / "model" / "artifacts" / "ppo_v1.0.0.pkl"
)
os.environ["MODEL_VERSION"] = "1.0.0"

import math
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rl_service import rl_service


@pytest.fixture(scope="module", autouse=True)
def client():
    if rl_service.agent is None:
        rl_service.load()
    with TestClient(app) as c:
        yield c


def make_rows(n=50, seed=42):
    """Genere n lignes OHLCV synthetiques (random walk)."""
    np.random.seed(seed)
    log_rets = np.random.normal(0.0005, 0.012, n)
    close = 100 * np.exp(np.cumsum(log_rets))
    rows = []
    for i, c in enumerate(close):
        rows.append({
            "Open":   float(c * 0.999),
            "High":   float(c * 1.005),
            "Low":    float(c * 0.995),
            "Close":  float(c),
            "Volume": float(np.random.randint(1_000_000, 50_000_000)),
        })
    return rows


# ---------------- 1. SUCCES ----------------
def test_predict_success(client):
    rows = make_rows(50)
    r = client.post("/predict", json={"rows": rows, "initial_cash": 10000})
    assert r.status_code == 200
    b = r.json()
    # Schema obligatoire
    for k in ["actions","labels","rewards","equity_curve","total_reward",
              "final_equity","cumulative_return","sharpe_ratio","max_drawdown",
              "win_rate","n_buy","n_hold","n_sell","n_steps","agent_version","duration_ms"]:
        assert k in b, f"Missing key: {k}"
    assert len(b["actions"]) == b["n_steps"]
    assert all(a in [0,1,2] for a in b["actions"])
    assert all(l in ["SELL","HOLD","BUY"] for l in b["labels"])


# ---------------- 2. INPUT INVALIDE ----------------
def test_predict_negative_price(client):
    rows = make_rows(15); rows[0]["Open"] = -1.0
    assert client.post("/predict", json={"rows": rows}).status_code == 422


def test_predict_zero_close(client):
    rows = make_rows(15); rows[5]["Close"] = 0.0
    assert client.post("/predict", json={"rows": rows}).status_code == 422


# ---------------- 3. PAYLOAD MANQUANT ----------------
def test_predict_missing_volume(client):
    rows = make_rows(15)
    for r in rows: del r["Volume"]
    assert client.post("/predict", json={"rows": rows}).status_code == 422


def test_predict_no_body(client):
    assert client.post("/predict", json={}).status_code == 422


# ---------------- 4. TROP COURT ----------------
def test_predict_too_few_rows(client):
    # Pydantic min_length=10 -> 422
    assert client.post("/predict", json={"rows": make_rows(5)}).status_code == 422


# ---------------- 5. META ENDPOINTS ----------------
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["agent_loaded"] is True


def test_version(client):
    r = client.get("/version")
    assert r.status_code == 200
    b = r.json()
    assert b["api_version"] == "1.0.0"
    assert b["agent_version"] == "1.0.0"
    assert b["framework"] == "stable-baselines3"


def test_metrics(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "total_requests" in r.json()


# ---------------- 6+7+8. INVARIANTS RL ----------------
def test_invariants(client):
    rows = make_rows(80)
    b = client.post("/predict", json={"rows": rows, "initial_cash": 5000}).json()
    # Sharpe est un float fini
    assert math.isfinite(b["sharpe_ratio"])
    # Comptage actions coherent
    assert b["n_buy"] + b["n_hold"] + b["n_sell"] == b["n_steps"]
    # equity_curve a 1 element de plus que rewards (point initial)
    assert len(b["equity_curve"]) == len(b["rewards"]) + 1
    # Cumulative return correctement calcule
    expected = (b["final_equity"] - 5000) / 5000
    assert abs(b["cumulative_return"] - expected) < 1e-6
