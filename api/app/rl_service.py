"""
Service RL - charge l'agent et rejoue un episode complet.

L'agent peut etre :
  (a) StubAgent (heuristique RSI/MACD) charge depuis .pkl (joblib)
  (b) Vrai PPO charge depuis .zip via stable_baselines3 (en prod)

Le choix est fait au moment du load: si le fichier finit par .zip ->
on tente sb3, sinon joblib.
"""
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .config import settings
from .trading_env import TradingEnv

ACTION_LABELS = {0: "SELL", 1: "HOLD", 2: "BUY"}


class RLService:
    """Singleton encapsulant l'agent + l'inference d'un episode."""

    def __init__(self):
        self.agent = None
        self.algo = "unknown"
        self.load_time_ms = 0.0

    def load(self):
        path = Path(settings.model_path)
        if not path.exists():
            raise FileNotFoundError(f"Agent not found at {path}")
        t0 = time.perf_counter()

        if path.suffix == ".zip":
            # Vrai PPO de SB3
            from stable_baselines3 import PPO
            self.agent = PPO.load(str(path))
            self.algo = "PPO"
        else:
            # Stub joblib (dev/test)
            self.agent = joblib.load(path)
            self.algo = getattr(self.agent, "algo", "stub")

        self.load_time_ms = (time.perf_counter() - t0) * 1000

    def run_episode(self, rows: list[dict], initial_cash: float = 10000.0):
        """Execute un episode complet et retourne metriques + trajectoire."""
        if self.agent is None:
            raise RuntimeError("Agent not loaded")
        if len(rows) < 10:
            raise ValueError("Need at least 10 rows to compute indicators")

        t0 = time.perf_counter()
        df = pd.DataFrame(rows)
        env = TradingEnv(df, initial_cash=initial_cash)
        obs, _ = env.reset(seed=42)

        actions, rewards, equity_curve = [], [], [initial_cash]
        done = False
        while not done:
            raw, _ = self.agent.predict(obs, deterministic=True)
            action = int(raw) if np.isscalar(raw) else int(raw.item())
            obs, reward, terminated, truncated, _ = env.step(action)
            actions.append(action)
            rewards.append(float(reward))
            equity_curve.append(float(env.equity))
            done = terminated or truncated

        # Compute episode-level metrics
        rewards_arr = np.array(rewards)
        eq_arr = np.array(equity_curve)
        daily_rets = np.diff(eq_arr) / (eq_arr[:-1] + 1e-9)
        sharpe = float(np.mean(daily_rets) / (np.std(daily_rets) + 1e-9) * np.sqrt(252))
        peak = np.maximum.accumulate(eq_arr)
        max_dd = float(np.min((eq_arr - peak) / peak))
        cum_ret = float((eq_arr[-1] - eq_arr[0]) / eq_arr[0])
        win_rate = float(np.mean(daily_rets > 0))

        labels = [ACTION_LABELS[a] for a in actions]
        result = {
            "actions": actions,
            "labels": labels,
            "rewards": rewards,
            "equity_curve": equity_curve,
            "total_reward": float(np.sum(rewards_arr)),
            "final_equity": float(eq_arr[-1]),
            "cumulative_return": cum_ret,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "n_buy":  int(np.sum(np.array(actions) == 2)),
            "n_hold": int(np.sum(np.array(actions) == 1)),
            "n_sell": int(np.sum(np.array(actions) == 0)),
            "n_steps": len(actions),
        }
        duration_ms = (time.perf_counter() - t0) * 1000
        return result, duration_ms


rl_service = RLService()


# ============================================================
# StubAgent : pour developpement local sans torch + SB3.
# Heuristique RSI/MACD. En PROD, remplace par PPO.load('.zip').
# ============================================================
class StubAgent:
    version = "1.0.0-stub"
    algo = "heuristic"

    def predict(self, obs, deterministic=True):
        rsi = obs[10]; macd = obs[11]; ma_signal = obs[12] + obs[13]
        if rsi > 0.7 and macd < 0:
            action = 0  # SELL
        elif rsi < 0.3 and ma_signal > 0:
            action = 2  # BUY
        else:
            action = 1  # HOLD
        return np.array(action), None
