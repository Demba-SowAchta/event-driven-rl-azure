"""
Worker Function - consume queue, call RL API, persist trajectory.

Idempotent: doc_id = blob_name + run_timestamp.
"""
import csv, io, json, logging, os, sys, time, uuid
from datetime import datetime, timezone

import azure.functions as func
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared import config, cosmos_client, storage_client

_session = requests.Session()
_session.headers.update({"Content-Type": "application/json"})


def _parse_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for raw in reader:
        try:
            row = {c: float(raw[c]) for c in config.EXPECTED_COLUMNS}
            rows.append(row)
        except (KeyError, ValueError) as exc:
            logging.warning("Skipped row: %s", exc)
    return rows


def main(msg: func.QueueMessage):
    t0 = time.perf_counter()
    job = json.loads(msg.get_body().decode("utf-8"))
    blob_name = job["blob_id"]
    container = job.get("blob_container", config.INPUT_CONTAINER)
    initial_cash = job.get("initial_cash", config.INITIAL_CASH)
    trace_id = job.get("trace_id", str(uuid.uuid4()))

    logging.info("Worker RL processing blob=%s trace=%s", blob_name, trace_id)

    csv_text = storage_client.download_blob_text(container, blob_name)
    rows = _parse_csv(csv_text)
    if len(rows) < 10:
        logging.warning("Too few rows in %s, skipping", blob_name)
        return

    # Call RL API
    api_t0 = time.perf_counter()
    resp = _session.post(f"{config.RL_API_URL}/predict",
                          json={"rows": rows, "initial_cash": initial_cash},
                          timeout=60)
    resp.raise_for_status()
    api_ms = (time.perf_counter() - api_t0) * 1000
    api_data = resp.json()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    doc_id = f"{blob_name.replace('/', '-')}-{ts}"

    # Persist full trajectory in output/
    full = {**api_data, "blob_name": blob_name, "trace_id": trace_id}
    storage_client.upload_blob_text(config.OUTPUT_CONTAINER, f"{doc_id}.json",
                                     json.dumps(full, indent=2))

    # Persist summary in Cosmos (without big arrays for query speed)
    cosmos_doc = {
        "id": doc_id,
        "blob_name": blob_name,
        "agent_version": api_data["agent_version"],
        "algo": api_data["algo"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_steps": api_data["n_steps"],
        "total_reward": api_data["total_reward"],
        "cumulative_return": api_data["cumulative_return"],
        "sharpe_ratio": api_data["sharpe_ratio"],
        "max_drawdown": api_data["max_drawdown"],
        "win_rate": api_data["win_rate"],
        "n_buy": api_data["n_buy"],
        "n_hold": api_data["n_hold"],
        "n_sell": api_data["n_sell"],
        "final_equity": api_data["final_equity"],
        # Garde un sub-sample du equity_curve pour le dashboard (max 50 points)
        "equity_curve": api_data["equity_curve"][::max(1, len(api_data["equity_curve"]) // 50)],
        "duration_ms": api_ms,
        "trace_id": trace_id,
        "output_blob": f"{config.OUTPUT_CONTAINER}/{doc_id}.json",
    }
    cosmos_client.upsert_episode(cosmos_doc)

    total_ms = (time.perf_counter() - t0) * 1000
    logging.info("Worker DONE blob=%s steps=%d reward=%.4f sharpe=%.2f total_ms=%.1f",
                 blob_name, api_data["n_steps"], api_data["total_reward"],
                 api_data["sharpe_ratio"], total_ms)
