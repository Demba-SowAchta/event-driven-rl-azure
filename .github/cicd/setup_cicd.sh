#!/usr/bin/env bash
# ====================================================================
# Setup CI/CD with OIDC authentication for GitHub Actions
# Run this once after the Azure infrastructure is deployed.
# Prints the 3 secrets + 4 variables to configure in the GitHub repo.
# ====================================================================
set -euo pipefail

: "${RG:?Set RG env var (e.g. rg-rlpipeline-dev)}"
: "${REPO:=Demba-SowAchta/event-driven-rl-azure}"
: "${ACR:?Set ACR env var}"
: "${FUNC_APP:?Set FUNC_APP env var}"
: "${CONTAINER_APP:=rl-api}"
: "${SP_NAME:=sp-event-driven-rl-deploy}"

SUB_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)

echo "[1/4] Creating Service Principal..."
APP_ID=$(az ad app create --display-name "$SP_NAME" --query appId -o tsv)
az ad sp create --id "$APP_ID" --only-show-errors >/dev/null

echo "[2/4] Assigning Contributor role on RG..."
sleep 10
az role assignment create --assignee "$APP_ID" --role "Contributor" \
    --scope "/subscriptions/$SUB_ID/resourceGroups/$RG" --only-show-errors >/dev/null

echo "[3/4] Configuring federated credentials..."
cat > /tmp/cred-main.json <<EOF
{ "name":"github-main",
  "issuer":"https://token.actions.githubusercontent.com",
  "subject":"repo:$REPO:ref:refs/heads/main",
  "audiences":["api://AzureADTokenExchange"] }
EOF
az ad app federated-credential create --id "$APP_ID" --parameters @/tmp/cred-main.json --only-show-errors >/dev/null

cat > /tmp/cred-staging.json <<EOF
{ "name":"github-staging",
  "issuer":"https://token.actions.githubusercontent.com",
  "subject":"repo:$REPO:environment:staging",
  "audiences":["api://AzureADTokenExchange"] }
EOF
az ad app federated-credential create --id "$APP_ID" --parameters @/tmp/cred-staging.json --only-show-errors >/dev/null

echo ""
echo "==========================================================="
echo "[4/4] GitHub configuration (manual step)"
echo "==========================================================="
echo "Open: https://github.com/$REPO/settings/secrets/actions"
echo "Add these SECRETS:"
echo "  AZURE_CLIENT_ID       = $APP_ID"
echo "  AZURE_TENANT_ID       = $TENANT_ID"
echo "  AZURE_SUBSCRIPTION_ID = $SUB_ID"
echo ""
echo "Open: https://github.com/$REPO/settings/variables/actions"
echo "Add these VARIABLES:"
echo "  RG             = $RG"
echo "  CONTAINER_APP  = $CONTAINER_APP"
echo "  FUNC_APP       = $FUNC_APP"
echo "  ACR_NAME       = $ACR"
echo ""
echo "Open: https://github.com/$REPO/settings/environments"
echo "Create environment named: staging"
echo ""
echo "[OK] Service Principal + federated credentials ready"
