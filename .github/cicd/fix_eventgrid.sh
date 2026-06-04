#!/usr/bin/env bash
# ====================================================================
# Fix Event Grid -> Function trigger that does not fire after deployment
# Root cause: Consumption-plan Functions need explicit trigger sync.
# ====================================================================
set -euo pipefail

: "${RG:?Set RG env var}"
: "${FUNC_APP:?Set FUNC_APP env var}"
: "${STORAGE:?Set STORAGE env var}"

SUB_ID=$(az account show --query id -o tsv)

echo "[1/4] Restarting Function App..."
az functionapp restart -g "$RG" -n "$FUNC_APP"

echo "[2/4] Forcing trigger synchronisation..."
az rest --method post --url \
  "https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.Web/sites/$FUNC_APP/syncfunctiontriggers?api-version=2016-08-01"

echo "[3/4] Waiting 90 seconds for warm-up..."
sleep 90

echo "[4/4] Re-creating Event Grid subscription..."
STORAGE_ID=$(az storage account show -n "$STORAGE" -g "$RG" --query id -o tsv)
DISPATCHER_ID="$(az functionapp show -n "$FUNC_APP" -g "$RG" --query id -o tsv)/functions/dispatcher"

az eventgrid event-subscription delete \
    --name "blob-input-created" --source-resource-id "$STORAGE_ID" 2>/dev/null || true

az eventgrid event-subscription create \
    --name "blob-input-created" \
    --source-resource-id "$STORAGE_ID" \
    --endpoint "$DISPATCHER_ID" --endpoint-type azurefunction \
    --included-event-types Microsoft.Storage.BlobCreated \
    --subject-begins-with "/blobServices/default/containers/input/"

echo ""
echo "[OK] Event Grid -> Function dispatcher is now fully active"
echo "Test: upload a CSV to input/ and check output/ and Cosmos within 60s"
