"""
Dispatcher Function (EventGridTrigger).

Declenchee par Event Grid quand un blob CSV est upload dans le conteneur
`input`. On valide le contenu et:
  - si OK     -> on enqueue un message JSON dans la queue `rl-jobs`
                  contenant le nom du blob + son hash
  - si KO     -> on copie le blob dans le conteneur `rejected` et on log
                  la raison

Cette separation dispatcher/worker existe pour 2 raisons:
  1. Le dispatcher est rapide (~50ms): valider un CSV, pas appeler le modele.
     Le worker peut prendre 1-5s car il appelle l'API RL via HTTP. Si on
     melange les deux dans une seule fonction, l'event grid timeout (30s)
     deviendrait risque sur des fichiers gros.
  2. La queue agit comme buffer: si l'API RL scale a 0 replica au moment
     ou un fichier arrive, le message reste en queue jusqu'a ce que la
     replica se reveille (cold-start ~6s pour Container Apps).
"""
import hashlib
import json
import logging
import sys
import os

import azure.functions as func

# Permet d'importer functions/shared sans setup.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared import config, storage_client


def _parse_blob_url(url: str) -> tuple[str, str]:
    """
    Event Grid envoie un blob URL du genre:
      https://<account>.blob.core.windows.net/input/spy_2024.csv
    On extrait (container, blob_name).
    """
    parts = url.split("/")
    # ['https:', '', '<account>.blob...', '<container>', '<blob_name>']
    container = parts[3]
    blob_name = "/".join(parts[4:])
    return container, blob_name


def _validate_csv(text: str) -> tuple[bool, str]:
    """
    Check rapide du CSV avant enqueue. Pas la peine de tout parser ici,
    le worker le refera. On verifie juste:
      - le header contient les 5 colonnes requises
      - au moins MIN_ROWS lignes de donnees
    """
    lines = [l for l in text.strip().split("\n") if l.strip()]
    if len(lines) < config.MIN_ROWS + 1:  # +1 pour header
        return False, f"Less than {config.MIN_ROWS} data rows"

    header = [c.strip() for c in lines[0].split(",")]
    missing = set(config.EXPECTED_COLUMNS) - set(header)
    if missing:
        return False, f"Missing columns: {sorted(missing)}"

    return True, ""


def main(event: func.EventGridEvent) -> None:
    """
    Entry point - le nom 'main' est impose par function.json.

    `event` est un EventGridEvent.  Pour Microsoft.Storage.BlobCreated
    le `data.url` contient l'URL complete du blob.
    """
    logging.info("Dispatcher event id=%s type=%s", event.id, event.event_type)

    data = event.get_json()
    blob_url = data.get("url", "")
    if not blob_url:
        logging.error("No 'url' field in event data")
        return

    container, blob_name = _parse_blob_url(blob_url)

    # On ne traite que les blobs deposes dans `input`. Si Event Grid envoie
    # autre chose par erreur (filtre mal configure), on ignore.
    if container != config.INPUT_CONTAINER:
        logging.info("Ignoring blob from container %s", container)
        return

    # Filtre extension (.csv uniquement, defini dans shared/config.py).
    ext = os.path.splitext(blob_name)[1].lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        logging.warning("Bad extension %s for %s -> reject", ext, blob_name)
        _reject(blob_name, f"bad extension: {ext}")
        return

    # Telecharger pour valider la structure.
    try:
        text = storage_client.download_blob_text(container, blob_name)
    except Exception as exc:
        logging.error("Download failed for %s: %s", blob_name, exc)
        return

    if len(text.encode("utf-8")) > config.MAX_FILE_SIZE_BYTES:
        _reject(blob_name, "file too large")
        return

    ok, err = _validate_csv(text)
    if not ok:
        _reject(blob_name, err)
        return

    # Hash pour idempotence cote worker (eviter un re-run si re-livraison
    # event grid - ca arrive sur les fonctions Consumption).
    blob_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]

    storage_client.enqueue_message(
        config.QUEUE_NAME,
        {
            "blob_name": blob_name,
            "blob_hash": blob_hash,
            "event_id": event.id,
        },
    )
    logging.info("Enqueued job for %s (hash=%s)", blob_name, blob_hash)


def _reject(blob_name: str, reason: str) -> None:
    """
    Copie le blob fautif dans `rejected` avec un sidecar .reason.txt qui
    explique pourquoi. Comme ca on garde une trace pour le post-mortem.
    """
    logging.warning("Reject %s: %s", blob_name, reason)
    try:
        storage_client.copy_blob(
            config.INPUT_CONTAINER, blob_name,
            config.REJECTED_CONTAINER, blob_name,
        )
        storage_client.upload_blob_text(
            config.REJECTED_CONTAINER, blob_name + ".reason.txt", reason
        )
        storage_client.delete_blob(config.INPUT_CONTAINER, blob_name)
    except Exception as exc:
        logging.error("Reject move failed for %s: %s", blob_name, exc)
