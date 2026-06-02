#!/usr/bin/env bash
# Bonus 1 - A/B Testing PPO (v1) vs DQN (v2) sur Container Apps
# Comparaison des algos via KQL.
set -euo pipefail
: "${RG:?}"
: "${CONT_APP:?}"
: "${ACR:?}"

# Active multi-revisions
az containerapp revision set-mode -n "$CONT_APP" -g "$RG" --mode multiple

# Deploye une 2eme image (DQN agent) avec ALGO=DQN
az containerapp update -n "$CONT_APP" -g "$RG" \
    --image "$ACR.azurecr.io/rl-api:2.0.0-dqn" \
    --revision-suffix dqn \
    --replace-env-vars ALGO=DQN MODEL_VERSION=2.0.0

REV_PPO=$(az containerapp revision list -n "$CONT_APP" -g "$RG" \
    --query "[?contains(name,'v1')].name | [0]" -o tsv)
REV_DQN=$(az containerapp revision list -n "$CONT_APP" -g "$RG" \
    --query "[?contains(name,'dqn')].name | [0]" -o tsv)

# Split 80/20
az containerapp ingress traffic set -n "$CONT_APP" -g "$RG" \
    --revision-weight "$REV_PPO=80" "$REV_DQN=20"

echo "A/B Testing:"
echo "  PPO (v1): 80%   - revision: $REV_PPO"
echo "  DQN (v2): 20%   - revision: $REV_DQN"
echo ""
echo "KQL pour comparer PPO vs DQN:"
cat << 'KQL'
customMetrics
| where name == "episode_reward"
| extend algo = tostring(customDimensions.algo)
| summarize mean=avg(value), p50=percentile(value,50),
            p95=percentile(value,95), n=count() by algo, bin(timestamp, 1h)
| render timechart
KQL
