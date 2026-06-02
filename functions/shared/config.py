import os

STORAGE_CONN = os.environ["AzureWebJobsStorage"]
COSMOS_CONN = os.environ.get("COSMOS_CONN", "")
COSMOS_DB = os.environ.get("COSMOS_DB", "rlpipeline")
COSMOS_CONTAINER = os.environ.get("COSMOS_CONTAINER", "episodes")
RL_API_URL = os.environ.get("RL_API_URL", "http://localhost:8000").rstrip("/")
QUEUE_NAME = os.environ.get("QUEUE_NAME", "rl-jobs")
REJECTED_CONTAINER = os.environ.get("REJECTED_CONTAINER", "rejected")
OUTPUT_CONTAINER = os.environ.get("OUTPUT_CONTAINER", "output")
INPUT_CONTAINER = os.environ.get("INPUT_CONTAINER", "input")
INITIAL_CASH = float(os.environ.get("INITIAL_CASH", "10000"))
MAX_FILE_SIZE_BYTES = int(os.environ.get("MAX_FILE_SIZE_BYTES", "10485760"))
ALLOWED_EXTENSIONS = {".csv"}
EXPECTED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
MIN_ROWS = 10
