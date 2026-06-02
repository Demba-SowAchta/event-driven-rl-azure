"""
Copie locale du TradingEnv pour l'API.
On evite d'importer model/ pour garder l'image Docker minimale.
"""
import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces


def compute_rsi(prices, period=14):
    delta = np.diff(prices, prepend=prices[0])
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    avg_up = pd.Series(up).rolling(period, min_periods=1).mean().values
    avg_down = pd.Series(down).rolling(period, min_periods=1).mean().values
    rs = avg_up / (avg_down + 1e-9)
    return (100 - 100 / (1 + rs)) / 100.0


def compute_macd(prices):
    s = pd.Series(prices)
    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    return ((ema12 - ema26) / s).fillna(0).values


class TradingEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, df, initial_cash=10000.0, transaction_cost=0.001, window=10):
        super().__init__()
        self.df = df.reset_index(drop=True).copy()
        self.n = len(self.df)
        self.initial_cash = initial_cash
        self.transaction_cost = transaction_cost
        self.window = window
        self.prices = self.df["Close"].values.astype(np.float64)
        self.volumes = self.df["Volume"].values.astype(np.float64)
        self.returns = np.diff(np.log(self.prices), prepend=0.0)
        self.rsi = compute_rsi(self.prices)
        self.macd = compute_macd(self.prices)
        self.ma20 = pd.Series(self.prices).rolling(20, min_periods=1).mean().values
        self.ma50 = pd.Series(self.prices).rolling(50, min_periods=1).mean().values
        self.vol_median = np.median(self.volumes) + 1e-9
        self.action_space = spaces.Discrete(3)
        self.observation_space = spaces.Box(low=-10.0, high=10.0, shape=(17,), dtype=np.float32)
        self.t = 0; self.cash = 0.0; self.position = 0
        self.equity = 0.0; self.prev_equity = 0.0

    def _obs(self):
        start = max(0, self.t - self.window + 1)
        rets = self.returns[start: self.t + 1]
        if len(rets) < self.window:
            rets = np.concatenate([np.zeros(self.window - len(rets)), rets])
        c = self.prices[self.t]
        return np.concatenate([rets.astype(np.float32), [
            float(self.rsi[self.t]),
            float(self.macd[self.t]),
            (c / self.ma20[self.t]) - 1.0 if self.ma20[self.t] > 0 else 0.0,
            (c / self.ma50[self.t]) - 1.0 if self.ma50[self.t] > 0 else 0.0,
            float(np.log((self.volumes[self.t] + 1e-9) / self.vol_median)),
            float(self.position),
            self.cash / self.initial_cash,
        ]]).astype(np.float32)

    def _equity(self):
        return self.cash + self.position * self.prices[self.t]

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.t = 0; self.cash = self.initial_cash; self.position = 0
        self.equity = self.initial_cash; self.prev_equity = self.initial_cash
        return self._obs(), {}

    def step(self, action):
        target = {0: -1, 1: self.position, 2: 1}[int(action)]
        delta = abs(target - self.position)
        if delta > 0:
            self.cash -= (target - self.position) * self.prices[self.t]
            self.cash -= self.transaction_cost * delta * self.prices[self.t]
            self.position = target
        self.t += 1
        terminated = self.t >= self.n - 1
        self.prev_equity = self.equity
        self.equity = self._equity()
        if self.prev_equity > 0 and self.equity > 0:
            reward = float(np.log(self.equity / self.prev_equity))
        else:
            reward = -1.0; terminated = True
        return self._obs(), reward, terminated, False, {}
