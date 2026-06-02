"""
Tests end-to-end de la pipeline RL.

Scenarios:
  1. Upload CSV OHLCV valide -> doc Cosmos sous 90s
  2. Upload CSV invalide (colonnes manquantes) -> rejected/
  3. Upload .txt -> rejected/

Usage:
    export STORAGE_CONN=... COSMOS_CONN=... RL_API_URL=...
    pytest tests/test_e2e.py -v
"""
import csv, io, os, time, uuid

import numpy as np
import pytest
import requests
from azure.cosmos import CosmosClient
from azure.storage.blob import BlobServiceClient

STORAGE_CONN = os.environ.get("STORAGE_CONN", "")
COSMOS_CONN = os.environ.get("COSMOS_CONN", "")
RL_API_URL = os.environ.get("RL_API_URL", "")

pytestmark = pytest.mark.skipif(
    not (STORAGE_CONN and COSMOS_CONN and RL_API_URL),
    reason="E2E tests need STORAGE_CONN, COSMOS_CONN, RL_API_URL"
)


def make_valid_csv(n=60, seed=42):
    rng = np.random.default_rng(seed)
    log_rets = rng.normal(0.0005, 0.012, n)
    close = 100 * np.exp(np.cumsum(log_rets))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Open", "High", "Low", "Close", "Volume"])
    for c in close:
        w.writerow([f"{c*0.999:.2f}", f"{c*1.005:.2f}",
                    f"{c*0.995:.2f}", f"{c:.2f}",
                    int(rng.integers(1_000_000, 50_000_000))])
    return buf.getvalue()


@pytest.fixture(scope="module")
def blob():
    return BlobServiceClient.from_connection_string(STORAGE_CONN)


@pytest.fixture(scope="module")
def cosmos_container():
    cli = CosmosClient.from_connection_string(COSMOS_CONN)
    db = cli.get_database_client("rlpipeline")
    return db.get_container_client("episodes")


def _wait_cosmos(container, blob_name, timeout=120):
    deadline = time.time() + timeout
    query = "SELECT * FROM c WHERE c.blob_name = @n ORDER BY c._ts DESC OFFSET 0 LIMIT 1"
    while time.time() < deadline:
        items = list(container.query_items(query=query,
            parameters=[{"name": "@n", "value": blob_name}],
            enable_cross_partition_query=True))
        if items: return items[0]
        time.sleep(5)
    return None


# ----- 1. Healthcheck RL API -----
def test_api_health():
    r = requests.get(f"{RL_API_URL}/health", timeout=10)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["agent_loaded"] is True


# ----- 2. Happy path: upload -> episode in Cosmos -----
def test_e2e_valid_episode(blob, cosmos_container):
    name = f"e2e-rl-{uuid.uuid4().hex[:8]}.csv"
    blob.get_blob_client("input", name).upload_blob(make_valid_csv(80), overwrite=True)

    doc = _wait_cosmos(cosmos_container, name, timeout=150)
    assert doc is not None, f"No episode in Cosmos for {name}"
    assert doc["algo"] in ("PPO", "DQN", "heuristic", "stub")
    assert doc["n_steps"] >= 70
    assert doc["n_buy"] + doc["n_hold"] + doc["n_sell"] == doc["n_steps"]
    assert "equity_curve" in doc and len(doc["equity_curve"]) > 0


# ----- 3. Invalid CSV (missing cols) -> rejected/ -----
def test_e2e_invalid_columns(blob):
    name = f"e2e-bad-{uuid.uuid4().hex[:8]}.csv"
    blob.get_blob_client("input", name).upload_blob(
        "wrong,header,cols\n1,2,3\n", overwrite=True)
    rej = blob.get_blob_client("rejected", name + ".error.json")
    deadline = time.time() + 60
    while time.time() < deadline:
        if rej.exists(): break
        time.sleep(3)
    assert rej.exists(), f"Bad CSV not rejected: {name}"


# ----- 4. Bad extension -----
def test_e2e_bad_extension(blob):
    name = f"e2e-bad-{uuid.uuid4().hex[:8]}.txt"
    blob.get_blob_client("input", name).upload_blob("not a csv", overwrite=True)
    rej = blob.get_blob_client("rejected", name + ".error.json")
    deadline = time.time() + 60
    while time.time() < deadline:
        if rej.exists(): break
        time.sleep(3)
    assert rej.exists()


# ----- 5. Too few rows -----
def test_e2e_too_few_rows(blob):
    name = f"e2e-short-{uuid.uuid4().hex[:8]}.csv"
    short = "Open,High,Low,Close,Volume\n" + "100,101,99,100,1000000\n" * 3
    blob.get_blob_client("input", name).upload_blob(short, overwrite=True)
    rej = blob.get_blob_client("rejected", name + ".error.json")
    deadline = time.time() + 60
    while time.time() < deadline:
        if rej.exists(): break
        time.sleep(3)
    assert rej.exists()
