# Notes theoriques RL pour la soutenance

## Pourquoi PPO ?
- **On-policy** : utilise des trajectoires generees par la politique courante.
- **Clipped objective** : evite les updates destructeurs (clip ratio 0.2).
- **Stable** : moins sensible aux hyperparametres que DDPG/SAC sur espaces discrets.
- **Implementation** : `stable_baselines3.PPO("MlpPolicy", env)`.

## MDP de notre TradingEnv
- **Etat (S)** : Box(17,) - 10 returns + RSI + MACD + 2x MA ratios + volume + position + cash ratio
- **Action (A)** : Discrete(3) - {0=SELL, 1=HOLD, 2=BUY}
- **Transition (P)** : deterministe (le marche evolue selon le CSV)
- **Reward (R)** : log-return - cout_transaction * |delta_position|
- **Discount (gamma)** : 0.99

## Pourquoi log-return ?
- Additif sur le temps : `sum(log_returns) = log(equity_final / equity_initial)`
- Plus stable numeriquement
- Symetrique : penalise autant gains que pertes

## Limites & extensions possibles
- **Overfitting** : un agent peut "memoriser" un dataset historique
- **Distribution shift** : marche 2024 != 2015, donc on backteste OOS
- **Risque** : pas de contrainte de drawdown dans le reward => extension via Lagrangien
- **Multi-asset** : extension naturelle - augmenter action_space + state_space
- **Continuous actions** : remplacer Discrete par Box(0,1) pour la taille de position

## Comparaison PPO vs DQN (bonus A/B)
| Aspect | PPO | DQN |
|--------|-----|-----|
| Type | On-policy, policy-gradient | Off-policy, value-based |
| Sample efficiency | Moyenne | Bonne (replay buffer) |
| Exploration | Stochastique via entropy | Epsilon-greedy |
| Stabilite training | Tres stable | Necessite target network |
| Actions continues | Oui (clip) | Non (juste discretes) |

Pour ce projet : on garde PPO en prod (plus stable, mieux sur petites donnees) et on teste DQN en A/B (20% du traffic) pour montrer la flexibilite de la pipeline.
