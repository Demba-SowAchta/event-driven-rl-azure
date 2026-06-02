"""
Backtest l'agent PPO sur un CSV out-of-sample.
Retourne: mean_reward, sharpe, max_drawdown, cumulative_return, win_rate.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from stable_baselines3 import PPO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_env import TradingEnv


def evaluate(model_path: str, csv_path: str) -> dict:
    model = PPO.load(model_path)
    df = pd.read_csv(csv_path, parse_dates=True, index_col=0)
    env = TradingEnv(df)
    obs, _ = env.reset()
    done = False
    rewards = []
    equity_curve = [env.initial_cash]
    actions = []
    while not done:
        action, _ = model.predict(obs, deterministic=True)
        action = int(action)
        obs, reward, terminated, truncated, _ = env.step(action)
        done = terminated or truncated
        rewards.append(float(reward))
        equity_curve.append(env.equity)
        actions.append(action)

    rewards_arr = np.array(rewards)
    equity_arr  = np.array(equity_curve)
    daily_returns = np.diff(equity_arr) / (equity_arr[:-1] + 1e-9)

    # Sharpe annualise (252 jours trading)
    sharpe = (np.mean(daily_returns) / (np.std(daily_returns) + 1e-9)) * np.sqrt(252)
    # Max drawdown
    peak = np.maximum.accumulate(equity_arr)
    dd = (equity_arr - peak) / peak
    max_dd = float(np.min(dd))
    cum_ret = (equity_arr[-1] - equity_arr[0]) / equity_arr[0]
    win_rate = float(np.mean(daily_returns > 0))

    return {
        "mean_reward": float(np.mean(rewards_arr)),
        "total_reward": float(np.sum(rewards_arr)),
        "cumulative_return": float(cum_ret),
        "sharpe_ratio": float(sharpe),
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "n_steps": len(rewards),
        "n_buy":  int(np.sum(np.array(actions) == 2)),
        "n_hold": int(np.sum(np.array(actions) == 1)),
        "n_sell": int(np.sum(np.array(actions) == 0)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--csv",   default="data/spy_eval.csv")
    args = parser.parse_args()
    print(json.dumps(evaluate(args.model, args.csv), indent=2))


if __name__ == "__main__":
    main()
