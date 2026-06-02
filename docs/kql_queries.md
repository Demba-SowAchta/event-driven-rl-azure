# RL Pipeline - KQL Queries

## Q1 - Reward moyen par heure
```kql
customMetrics
| where name == "episode_reward"
| summarize avg_reward = avg(value), p95 = percentile(value, 95) by bin(timestamp, 1h)
| render timechart
```

## Q2 - Distribution actions (BUY/HOLD/SELL)
```kql
customEvents
| where name == "EpisodeCompleted"
| extend b=todouble(customMeasurements.n_buy),
         h=todouble(customMeasurements.n_hold),
         s=todouble(customMeasurements.n_sell)
| summarize BUY=sum(b), HOLD=sum(h), SELL=sum(s)
| render piechart
```

## Q3 - Top 5 episodes les plus rentables
```kql
customEvents
| where name == "EpisodeCompleted"
| extend ret = todouble(customMeasurements.cumulative_return)
| project timestamp, blob = tostring(customDimensions.blob_name), ret, sharpe = todouble(customMeasurements.sharpe_ratio)
| top 5 by ret desc
```

## Q4 - Sharpe ratio distribution par algo (pour A/B test PPO vs DQN)
```kql
customMetrics
| where name == "episode_sharpe"
| extend algo = tostring(customDimensions.algo)
| summarize p50=percentile(value,50), p95=percentile(value,95),
            mean=avg(value), n=count() by algo
```

## Q5 - Latence par algo (bonus debug)
```kql
customMetrics
| where name == "inference_latency_ms"
| extend algo = tostring(customDimensions.algo)
| summarize p50=percentile(value,50), p95=percentile(value,95)
            by algo, bin(timestamp, 5m)
| render timechart
```

## Custom metrics emises (>=3)
| Metric              | Description |
|---------------------|-------------|
| `episode_reward`    | Reward total de l'episode |
| `episode_sharpe`    | Sharpe ratio annualise |
| `inference_latency_ms` | Latence d'un episode |

## Alertes (>=2)
1. `api_error_rate > 5%` sur 5 min - sev 2
2. `p95(inference_latency_ms) > 5s` sur 5 min - sev 2
