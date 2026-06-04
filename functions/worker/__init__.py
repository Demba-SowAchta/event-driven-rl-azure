"""
Worker Function (QueueTrigger sur rl-jobs).

Pour chaque job en queue:
  1. Telecharger le CSV depuis le conteneur `input`
  2. Parser le CSV en list[dict] OHLCV
  3. POST /predict sur l'API RL (Container Apps)
  4. Upload du JSON resultat dans le conteneur `output`
  5. Upsert d'un document Cosmos dans la collection `episodes`
  6. (optionnel) Enrichir le doc avec un commentaire LLM Hugging Face

Si une etape echoue, l'exception remonte et la queue Azure re-livre le
message jusqu'a maxDequeueCount (5 par defaut, configure dans host.json).
Apres 5 echecs, le message file en queue `rl-jobs-poison`.
"""
import csv
import io
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import azure.functions as func
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared import config, cosmos_client, storage_client

# LLM commentary est facultatif (token HuggingFace optionnel).
try:
    from shared.llm_commentary import market_commentary
except Exception:
    market_commentary = lambda doc: None  # noqa: E731


def _parse_csv(text: str) -> list[dict]:
    """
    Parse le CSV en liste de dicts.  L'API attend les colonnes
    Open/High/Low/Close/Volume en float strict (Pydantic gt=0).
    Si une cellule est vide ou non-numerique, on raise pour partir
    en poison queue (= input clairement invalide).
    """
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        rows.append({
            "Open":   float(row["Open"]),
            "High":   float(row["High"]),
            "Low":    float(row["Low"]),
            "Close":  float(row["Close"]),
            "Volume": float(row["Volume"]),
        })
    return rows


def main(msg: func.QueueMessage) -> None:
    """
    Entry point du worker.

    `msg` est un QueueMessage Azure.  Le body est base64-decode par le
    runtime (cf. host.json: BinaryBase64EncodePolicy cote producer).
    On JSON-load et on a un dict {blob_name, blob_hash, event_id}.
    """
    job = json.loads(msg.get_body().decode("utf-8"))
    blob_name = job["blob_name"]
    blob_hash = job.get("blob_hash", "?")
    logging.info("Worker start blob=%s hash=%s", blob_name, blob_hash)

    t_start = time.perf_counter()

    # 1. Telecharger le CSV
    text = storage_client.download_blob_text(config.INPUT_CONTAINER, blob_name)
    try:
        rows = _parse_csv(text)
    except (ValueError, KeyError) as exc:
        logging.error("CSV parse failed for %s: %s", blob_name, exc)
        raise  # -> poison queue, l'operateur regarde

    if len(rows) < config.MIN_ROWS:
        raise ValueError(f"only {len(rows)} rows, need {config.MIN_ROWS}")

    # 2. Appeler l'API RL
    payload = {"rows": rows, "initial_cash": config.INITIAL_CASH}
    resp = requests.post(
        f"{config.RL_API_URL}/predict",
        json=payload,
        timeout=120,  # Container Apps cold-start peut prendre 30s
    )
    resp.raise_for_status()
    result = resp.json()

    # 3. Sauver le resultat brut dans `output`
    output_blob_name = blob_name.replace(".csv", "") + "_result.json"
    storage_client.upload_blob_text(
        config.OUTPUT_CONTAINER,
        output_blob_name,
        json.dumps(result, indent=2),
    )

    # 4. Construire le document Cosmos.
    # `agent_version` est notre partition key (cf. main.bicep).
    doc = {
        "id": f"{blob_name}-{blob_hash}-{int(time.time())}",
        "blob_name": blob_name,
        "blob_hash": blob_hash,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_version": result["agent_version"],
        "algo": result["algo"],
        "n_steps": result["n_steps"],
        "total_reward": result["total_reward"],
        "cumulative_return": result["cumulative_return"],
        "sharpe_ratio": result["sharpe_ratio"],
        "max_drawdown": result["max_drawdown"],
        "win_rate": result["win_rate"],
        "n_buy": result["n_buy"],
        "n_hold": result["n_hold"],
        "n_sell": result["n_sell"],
        "duration_ms": result["duration_ms"],
        # On garde la courbe d'equity pour l'affichage dashboard.
        "equity_curve": result["equity_curve"],
        "worker_duration_ms": round((time.perf_counter() - t_start) * 1000, 1),
    }

    # 5. (optionnel) commentaire LLM
    try:
        commentary = market_commentary(doc)
        if commentary:
            doc["llm_commentary"] = commentary
    except Exception as exc:
        # On ne fait pas echouer le job pour un LLM down - c'est bonus.
        logging.warning("LLM commentary skipped: %s", exc)

    cosmos_client.upsert_episode(doc)
    logging.info(
        "Worker done blob=%s return=%.2f%% sharpe=%.2f ms=%d",
        blob_name,
        result["cumulative_return"] * 100,
        result["sharpe_ratio"],
        doc["worker_duration_ms"],
    )
