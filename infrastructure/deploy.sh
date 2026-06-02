#!/usr/bin/env bash
# =================================================================
# Deploiement complet du pipeline RL event-driven sur Azure
# Usage: bash deploy.sh
# =================================================================
set -euo pipefail

export ENV_NAME="${ENV_NAME:-dev}"
export RG="${RG:-rg-rlpipeline-$ENV_NAME}"
export LOC="${LOC:-francecentral}"
RAND="${RANDOM}${RANDOM:0:2}"
export STORAGE="${STORAGE:-strlpipe$ENV_NAME$RAND}"
export ACR="${ACR:-acrrlpipe$ENV_NAME$RAND}"
export COSMOS="${COSMOS:-cosmos-rlpipe-$ENV_NAME-$RAND}"
export FUNC_APP="${FUNC_APP:-func-rlpipe-$ENV_NAME-$RAND}"
export CONT_APP="${CONT_APP:-rl-api}"
export CONT_ENV_NAME="${CONT_ENV_NAME:-cae-rlpipe-$ENV_NAME}"
export APPI="${APPI:-appi-rlpipe-$ENV_NAME}"
export LAW="${LAW:-law-rlpipe-$ENV_NAME}"
export SWA="${SWA:-swa-rlpipe-$ENV_NAME}"
export AGENT_TAG="${AGENT_TAG:-1.0.0}"

echo "[INFO] Deploying RL environment '$ENV_NAME' in $LOC"

# 1. Resource group
az group create -n "$RG" -l "$LOC" -o none
echo "[OK] RG $RG"

# 2. Observabilite
az monitor log-analytics workspace create -g "$RG" -n "$LAW" \
    --quota 1 --retention-time 30 -o none
LAW_ID=$(az monitor log-analytics workspace show -g "$RG" -n "$LAW" --query customerId -o tsv)
LAW_KEY=$(az monitor log-analytics workspace get-shared-keys -g "$RG" -n "$LAW" --query primarySharedKey -o tsv)
az monitor app-insights component create -g "$RG" -a "$APPI" -l "$LOC" --workspace "$LAW" -o none
APPI_CONN=$(az monitor app-insights component show -g "$RG" -a "$APPI" --query connectionString -o tsv)
echo "[OK] App Insights"

# 3. Storage + containers + queues
az storage account create -n "$STORAGE" -g "$RG" -l "$LOC" --sku Standard_LRS -o none
STORAGE_CONN=$(az storage account show-connection-string -n "$STORAGE" -g "$RG" -o tsv)
for c in input output models rejected; do
  az storage container create --name "$c" --connection-string "$STORAGE_CONN" -o none
done
az storage account blob-service-properties update -g "$RG" \
    --account-name "$STORAGE" --enable-versioning true -o none
az storage queue create --name rl-jobs --connection-string "$STORAGE_CONN" -o none
az storage queue create --name rl-jobs-poison --connection-string "$STORAGE_CONN" -o none
echo "[OK] Storage + queues"

# 4. Cosmos Free Tier
az cosmosdb create -n "$COSMOS" -g "$RG" --kind GlobalDocumentDB \
    --enable-free-tier true --default-consistency-level Session \
    --locations regionName="$LOC" failoverPriority=0 isZoneRedundant=false -o none
az cosmosdb sql database create -a "$COSMOS" -g "$RG" -n rlpipeline -o none
az cosmosdb sql container create -a "$COSMOS" -g "$RG" -d rlpipeline \
    -n episodes --partition-key-path "/agent_version" --throughput 400 -o none
COSMOS_CONN=$(az cosmosdb keys list --type connection-strings -n "$COSMOS" -g "$RG" \
    --query connectionStrings[0].connectionString -o tsv)
echo "[OK] Cosmos"

# 5. ACR + push image (RL image plus grosse, 0.5 CPU/1Gi)
az acr create -n "$ACR" -g "$RG" --sku Basic --admin-enabled true -o none
az acr login -n "$ACR"
echo "[INFO] Building RL Docker image (large, ~700 MB with torch)..."
docker build -t "$ACR.azurecr.io/rl-api:$AGENT_TAG" -f ../api/Dockerfile ../api
docker push "$ACR.azurecr.io/rl-api:$AGENT_TAG"
ACR_USER=$(az acr credential show -n "$ACR" --query username -o tsv)
ACR_PASS=$(az acr credential show -n "$ACR" --query passwords[0].value -o tsv)
echo "[OK] Image pushed"

# 6. Container Apps Env + RL API
az extension add --name containerapp --upgrade -y >/dev/null
az containerapp env create -n "$CONT_ENV_NAME" -g "$RG" -l "$LOC" \
    --logs-workspace-id "$LAW_ID" --logs-workspace-key "$LAW_KEY" -o none
az containerapp create -n "$CONT_APP" -g "$RG" \
    --environment "$CONT_ENV_NAME" \
    --image "$ACR.azurecr.io/rl-api:$AGENT_TAG" \
    --registry-server "$ACR.azurecr.io" \
    --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --cpu 0.5 --memory 1Gi \
    --min-replicas 0 --max-replicas 3 \
    --ingress external --target-port 8000 \
    --env-vars APPLICATIONINSIGHTS_CONNECTION_STRING="$APPI_CONN" \
               MODEL_VERSION="$AGENT_TAG" -o none
RL_API_FQDN=$(az containerapp show -n "$CONT_APP" -g "$RG" \
    --query properties.configuration.ingress.fqdn -o tsv)
RL_API_URL="https://$RL_API_FQDN"
echo "[OK] RL API at $RL_API_URL"

# 7. Function App
az functionapp create -g "$RG" -n "$FUNC_APP" --consumption-plan-location "$LOC" \
    --runtime python --runtime-version 3.11 --functions-version 4 \
    --storage-account "$STORAGE" --os-type Linux --app-insights "$APPI" -o none
az functionapp config appsettings set -g "$RG" -n "$FUNC_APP" --settings \
    COSMOS_CONN="$COSMOS_CONN" COSMOS_DB="rlpipeline" COSMOS_CONTAINER="episodes" \
    RL_API_URL="$RL_API_URL" QUEUE_NAME="rl-jobs" \
    REJECTED_CONTAINER="rejected" OUTPUT_CONTAINER="output" INPUT_CONTAINER="input" \
    INITIAL_CASH="10000" MAX_FILE_SIZE_BYTES="10485760" \
    APPLICATIONINSIGHTS_CONNECTION_STRING="$APPI_CONN" -o none

echo "[INFO] Publishing Functions..."
(cd ../functions && func azure functionapp publish "$FUNC_APP" --python)

# 8. Event Grid subscription
STORAGE_ID=$(az storage account show -n "$STORAGE" -g "$RG" --query id -o tsv)
DISPATCHER_ID="$(az functionapp show -n "$FUNC_APP" -g "$RG" --query id -o tsv)/functions/dispatcher"
az eventgrid event-subscription create \
    --name "blob-input-created-$ENV_NAME" \
    --source-resource-id "$STORAGE_ID" --endpoint "$DISPATCHER_ID" \
    --endpoint-type azurefunction \
    --included-event-types Microsoft.Storage.BlobCreated \
    --subject-begins-with "/blobServices/default/containers/input/" -o none

# 9. Alertes
APPI_ID=$(az monitor app-insights component show -g "$RG" -a "$APPI" --query id -o tsv)
az monitor metrics alert create -g "$RG" -n "alert-error-rate-$ENV_NAME" \
    --scopes "$APPI_ID" --condition "avg requests/failed > 5" \
    --window-size 5m --evaluation-frequency 1m --severity 2 -o none
# Latency seuil plus haut pour RL (episodes peuvent durer plus longtemps)
az monitor metrics alert create -g "$RG" -n "alert-p95-latency-$ENV_NAME" \
    --scopes "$APPI_ID" --condition "percentile requests/duration 95 > 5000" \
    --window-size 5m --evaluation-frequency 1m --severity 2 -o none

# 10. Budget
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
START_DATE=$(date +%Y-%m-01)
END_DATE=$(date -d "+1 year" +%Y-%m-01 2>/dev/null || date -v+1y +%Y-%m-01)
az consumption budget create --budget-name "budget-rlpipe-$ENV_NAME" \
    --amount 80 --category cost --time-grain Monthly \
    --start-date "$START_DATE" --end-date "$END_DATE" 2>/dev/null || \
    echo "[WARN] Budget needs scope rights"

echo ""
echo "================================================================"
echo "RL DEPLOYMENT COMPLETE - Environment: $ENV_NAME"
echo "================================================================"
echo "RG          : $RG"
echo "RL API URL  : $RL_API_URL"
echo "Function App: https://$FUNC_APP.azurewebsites.net"
echo ""
echo "Test:"
echo "  curl $RL_API_URL/health"
echo "  az storage blob upload --account-name $STORAGE -c input -f spy_test.csv"
echo ""
echo "Cleanup:"
echo "  az group delete -n $RG --yes --no-wait"
