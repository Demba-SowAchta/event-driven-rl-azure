#!/usr/bin/env bash
# Bonus 3 - APIM Consumption (gratuit jusqu'a 1M calls/mois) pour RL API
set -euo pipefail
: "${RG:?}"
: "${APIM:=apim-rlpipe-$ENV_NAME}"
: "${RL_API_URL:?}"

az apim create -n "$APIM" -g "$RG" \
    --publisher-email "$(az account show --query user.name -o tsv)" \
    --publisher-name "ECE RLPipeline" \
    --sku-name Consumption -o none

az apim api import -g "$RG" -n "$APIM" \
    --path /rl --api-id rl-trading-api \
    --specification-url "$RL_API_URL/openapi.json" \
    --specification-format OpenApi -o none

sed "s|<env>|$ENV_NAME|" apim_policy.xml > /tmp/policy.xml
az apim api policy create -g "$RG" --service-name "$APIM" \
    --api-id rl-trading-api --policy-format xml \
    --value "$(cat /tmp/policy.xml)" -o none

APIM_URL=$(az apim show -g "$RG" -n "$APIM" --query gatewayUrl -o tsv)
KEY=$(az apim subscription show -g "$RG" --service-name "$APIM" \
    --sid "default-sub" --query primaryKey -o tsv 2>/dev/null || echo "<get-via-portal>")

echo ""
echo "APIM ready for RL API:"
echo "  Gateway:  $APIM_URL/rl/predict"
echo "  Sub key:  Ocp-Apim-Subscription-Key: $KEY"
