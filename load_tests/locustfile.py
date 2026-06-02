"""
Bonus 2 - Load testing avec Locust.

Genere 100 utilisateurs simultanes uploadant des CSV OHLCV de 252 lignes
pour stresser le pipeline RL et observer l'autoscale Container Apps.

Usage:
    pip install locust azure-storage-blob
    export STORAGE_CONN="DefaultEndpointsProtocol=..."
    locust -f locustfile.py --host=https://dummy \
           --users 100 --spawn-rate 10 --run-time 5m --headless
"""
import csv, io, os, random, time, uuid
import numpy as np
from azure.storage.blob import BlobServiceClient
from locust import HttpUser, between, events, task

STORAGE_CONN = os.environ.get("STORAGE_CONN", "")
CONTAINER = os.environ.get("INPUT_CONTAINER", "input")
_bs = None


def get_blob_service():
    global _bs
    if _bs is None and STORAGE_CONN:
        _bs = BlobServiceClient.from_connection_string(STORAGE_CONN)
    return _bs


def make_ohlcv_csv(n=252, seed=None):
    """Random walk synthetique."""
    if seed is None:
        seed = random.randint(1, 10**6)
    rng = np.random.default_rng(seed)
    log_rets = rng.normal(0.0005, 0.012, n)
    close = 100 * np.exp(np.cumsum(log_rets))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Open", "High", "Low", "Close", "Volume"])
    for c in close:
        w.writerow([
            f"{c*0.999:.2f}", f"{c*1.005:.2f}",
            f"{c*0.995:.2f}", f"{c:.2f}",
            int(rng.integers(1_000_000, 50_000_000)),
        ])
    return buf.getvalue()


class TradingDataUploader(HttpUser):
    """Chaque user uploade un CSV OHLCV vers Blob Storage."""
    wait_time = between(2, 5)

    @task
    def upload_csv(self):
        bs = get_blob_service()
        if bs is None:
            return
        name = f"loadtest-{uuid.uuid4().hex[:8]}-{int(time.time())}.csv"
        n_rows = random.choice([60, 120, 252])
        content = make_ohlcv_csv(n=n_rows)
        t0 = time.perf_counter()
        try:
            bs.get_blob_client(container=CONTAINER, blob=name) \
              .upload_blob(content, overwrite=True)
            dur = (time.perf_counter() - t0) * 1000
            events.request.fire(request_type="UPLOAD", name=f"csv_{n_rows}rows",
                                response_time=dur, response_length=len(content),
                                exception=None)
        except Exception as exc:
            events.request.fire(request_type="UPLOAD", name=name,
                                response_time=0, response_length=0, exception=exc)
