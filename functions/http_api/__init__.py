"""HTTP API serving the dashboard. Rate limited 60/min/IP."""
import json, logging, os, sys, time
from collections import defaultdict, deque

import azure.functions as func

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared import cosmos_client

_REQS, _LIMIT, _WINDOW = defaultdict(deque), 60, 60


def _check_rate(ip):
    now = time.time()
    dq = _REQS[ip]
    while dq and now - dq[0] > _WINDOW: dq.popleft()
    if len(dq) >= _LIMIT: return False
    dq.append(now); return True


def main(req: func.HttpRequest) -> func.HttpResponse:
    ip = req.headers.get("x-forwarded-for", "unknown").split(",")[0].strip()
    if not _check_rate(ip):
        return func.HttpResponse(json.dumps({"error": "Rate limit exceeded"}),
                                  status_code=429, mimetype="application/json")
    try:
        limit = min(max(int(req.params.get("limit", "20")), 1), 100)
    except ValueError:
        limit = 20
    try:
        items = cosmos_client.list_recent(limit=limit)
    except Exception as exc:
        logging.error("Cosmos error: %s", exc)
        return func.HttpResponse(json.dumps({"error": "Internal error"}),
                                  status_code=500, mimetype="application/json")
    return func.HttpResponse(
        json.dumps({"count": len(items), "items": items}),
        status_code=200, mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"})
