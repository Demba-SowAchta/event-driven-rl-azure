"""
Trading Environment - Gymnasium custom env.

L'agent observe l'etat du marche et choisit BUY / HOLD / SELL pour
maximiser le rendement cumule.

MDP:
  - Etat: 17-dim vector (returns, RSI, MACD, MA ratio, volume, position, cash, equity)
  - Action: discrete 3 (0=SELL, 1=HOLD, 2=BUY)
  - Reward: log return - transaction_cost
"""
import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces


def compute_rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index."""
    delta = np.diff(prices, prepend=prices[0])
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    avg_up = pd.Series(up).rolling(period, min_periods=1).mean().values
    avg_down = pd.Series(down).rolling(period, min_periods=1).mean().values
    rs = avg_up / (avg_down + 1e-9)
    rsi = 100 - 100 / (1 + rs)
    return rsi / 100.0  # normalize to [0,1]


def compute_macd(prices: np.ndarray) -> np.ndarray:
    """Normalized MACD signal."""
    s = pd.Series(prices)
    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    macd = (ema12 - ema26) / s
    return macd.fillna(0).values


class TradingEnv(gym.Env):
    """Single-asset trading environment.

    Observation (17 dims):
      0-9   : last 10 normalized returns (log-returns)
      10    : RSI (normalized 0..1)
      11    : MACD signal (normalized)
      12    : Close / MA20 ratio
      13    : Close / MA50 ratio
      14    : log(Volume / median_volume)
      15    : current position (-1, 0, 1)
      16    : cash ratio (cash / initial_cash)

    Actions:
      0 = SELL (target position = -1, sells all and goes short)
      1 = HOLD (target position unchanged)
      2 = BUY  (target position = +1)

    Reward = log(equity_t / equity_{t-1}) - transaction_cost * |position_change|
    """

    metadata = {"render_modes": []}

    def __init__(self, df: pd.DataFrame, initial_cash: float = 10000.0,
                 transaction_cost: float = 0.001, window: int = 10):
        super().__init__()
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            raise ValueError(f"DataFrame missing cols: {required - set(df.columns)}")

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
        self.observation_space = spaces.Box(
            low=-10.0, high=10.0, shape=(17,), dtype=np.float32
        )

        # Internal state (set in reset)
        self.t = 0
        self.cash = 0.0
        self.position = 0   # -1 short, 0 flat, +1 long
        self.equity = 0.0
        self.prev_equity = 0.0
        self.history = []

    def _obs(self) -> np.ndarray:
        # last 10 returns (padded)
        start = max(0, self.t - self.window + 1)
        rets = self.returns[start: self.t + 1]
        if len(rets) < self.window:
            rets = np.concatenate([np.zeros(self.window - len(rets)), rets])
        rets = rets.astype(np.float32)

        rsi = float(self.rsi[self.t])
        macd = float(self.macd[self.t])
        c = self.prices[self.t]
        ma20_r = (c / self.ma20[self.t]) - 1.0 if self.ma20[self.t] > 0 else 0.0
        ma50_r = (c / self.ma50[self.t]) - 1.0 if self.ma50[self.t] > 0 else 0.0
        vol_r = float(np.log((self.volumes[self.t] + 1e-9) / self.vol_median))
        pos = float(self.position)
        cash_r = self.cash / self.initial_cash

        obs = np.concatenate([
            rets,
            [rsi, macd, ma20_r, ma50_r, vol_r, pos, cash_r],
        ]).astype(np.float32)
        return obs

    def _equity(self) -> float:
        # Mark-to-market: cash + position * price (units = shares of $100 notional)
        return self.cash + self.position * self.prices[self.t]

    def reset(self, *, seed: int | None = None, options=None):
        super().reset(seed=seed)
        self.t = 0
        self.cash = self.initial_cash
        self.position = 0
        self.equity = self.initial_cash
        self.prev_equity = self.initial_cash
        self.history = []
        return self._obs(), {}

    def step(self, action: int):
        prev_position = self.position
        # Map action to target position
        target = {0: -1, 1: self.position, 2: 1}[int(action)]
        # If position changes, apply transaction cost
        delta = abs(target - self.position)
        tx_cost = 0.0
        if delta > 0:
            # Cash adjustment: buying/selling notional 100 at current price
            self.cash -= (target - self.position) * self.prices[self.t]
            tx_cost = self.transaction_cost * delta * self.prices[self.t]
            self.cash -= tx_cost
            self.position = target

        # Advance time
        self.t += 1
        terminated = self.t >= self.n - 1
        truncated = False

        self.prev_equity = self.equity
        self.equity = self._equity()
        # Log-return reward
        if self.prev_equity > 0 and self.equity > 0:
            reward = float(np.log(self.equity / self.prev_equity))
        else:
            reward = -1.0   # bankrupt
            terminated = True

        self.history.append({
            "t": self.t, "action": int(action), "position": self.position,
            "price": float(self.prices[self.t]), "equity": float(self.equity),
            "reward": reward,
        })

        return self._obs(), reward, terminated, truncated, {}

    def render(self):
        pass
