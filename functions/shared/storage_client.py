import json
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueServiceClient, BinaryBase64EncodePolicy
from . import config

_blob, _queue = None, None


def blob_service():
    global _blob
    if _blob is None: _blob = BlobServiceClient.from_connection_string(config.STORAGE_CONN)
    return _blob


def queue_service():
    global _queue
    if _queue is None: _queue = QueueServiceClient.from_connection_string(config.STORAGE_CONN)
    return _queue


def get_blob_client(container, name): return blob_service().get_blob_client(container=container, blob=name)
def download_blob_text(c, n): return get_blob_client(c, n).download_blob().readall().decode("utf-8")
def upload_blob_text(c, n, t): get_blob_client(c, n).upload_blob(t, overwrite=True)
def delete_blob(c, n): get_blob_client(c, n).delete_blob(delete_snapshots="include")


def copy_blob(sc, sn, dc, dn):
    s = get_blob_client(sc, sn); d = get_blob_client(dc, dn)
    d.start_copy_from_url(s.url)


def enqueue_message(name, payload):
    qc = queue_service().get_queue_client(name)
    qc.message_encode_policy = BinaryBase64EncodePolicy()
    qc.send_message(json.dumps(payload).encode("utf-8"))
