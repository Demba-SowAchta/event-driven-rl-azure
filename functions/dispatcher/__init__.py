"""
Dispatcher Function - Event Grid Trigger.

Valide le CSV OHLCV upload (extension, taille, schema, min 10 lignes)
puis enqueue dans Storage Queue 'rl-jobs'.
"""
import io, json, logging, os, sys, csv
from datetime import datetime, timezone

import azure.functions as func

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared import config, storage_client


def _parse_subject(subject):
    parts = subject.split("/")
    return parts[parts.index("containers") + 1], "/".join(parts[parts.index("blobs") + 1:])


def _is_valid_ohlcv(content):
    try:
        text = content.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        header = next(reader, [])
        missing = set(config.EXPECTED_COLUMNS) - set(h.strip() for h in header)
        if missing:
            return False, f"Missing columns: {sorted(missing)}"
        rows = list(reader)
        if len(rows) < config.MIN_ROWS:
            return False, f"Need at least {config.MIN_ROWS} rows, got {len(rows)}"
        # Spot check first row
        for v in rows[0][:5]:
            float(v)
        return True, ""
    except UnicodeDecodeError:
        return False, "Not valid UTF-8"
    except Exception as exc:
        return False, f"CSV error: {exc}"


def main(event: func.EventGridEvent):
    body = event.get_json()
    if event.event_type != "Microsoft.Storage.BlobCreated":
        return
    try:
        container, blob_name = _parse_subject(event.subject)
    except Exception:
        return
    if container != config.INPUT_CONTAINER:
        return

    size = int(body.get("contentLength", 0))
    if size > config.MAX_FILE_SIZE_BYTES:
        return _reject(container, blob_name, f"Too large: {size}")

    if os.path.splitext(blob_name)[1].lower() not in config.ALLOWED_EXTENSIONS:
        return _reject(container, blob_name, "Invalid extension")

    try:
        content = storage_client.get_blob_client(container, blob_name).download_blob().readall()
    except Exception as exc:
        logging.error("Download failed: %s", exc); return

    ok, reason = _is_valid_ohlcv(content)
    if not ok:
        return _reject(container, blob_name, reason)

    msg = {
        "blob_id": blob_name, "blob_container": container,
        "blob_url": body.get("url", ""), "size": size,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "trace_id": event.id,
        "initial_cash": config.INITIAL_CASH,
    }
    storage_client.enqueue_message(config.QUEUE_NAME, msg)
    logging.info("Enqueued RL job blob=%s size=%d", blob_name, size)


def _reject(container, blob_name, reason):
    logging.warning("REJECTED %s: %s", blob_name, reason)
    err = {"original_blob": blob_name, "reason": reason,
           "rejected_at": datetime.now(timezone.utc).isoformat()}
    try:
        storage_client.upload_blob_text(config.REJECTED_CONTAINER,
                                        blob_name + ".error.json",
                                        json.dumps(err, indent=2))
        storage_client.copy_blob(container, blob_name, config.REJECTED_CONTAINER, blob_name)
        storage_client.delete_blob(container, blob_name)
    except Exception as exc:
        logging.error("Reject failed: %s", exc)
