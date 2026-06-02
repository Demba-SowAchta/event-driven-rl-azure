"""
Bonus - Entraine un agent DQN concurrent pour A/B test vs PPO.

Usage: python train_dqn.py --version 2.0.0 --timesteps 50000
"""
import argparse, os, sys
from pathlib import Path
import numpy as np
import pandas as pd
from stable_baselines3 import DQN
from stable_baselines3.common.vec_env import DummyVecEnv, VecMonitor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_env import TradingEnv

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--version", required=True)
    p.add_argument("--train-csv", default="data/spy_train.csv")
    p.add_argument("--timesteps", type=int, default=50_000)
    p.add_argument("--out-dir", default="artifacts")
    args = p.parse_args()

    np.random.seed(42)
    df = pd.read_csv(args.train_csv, parse_dates=True, index_col=0)
    df.columns = [c.title() for c in df.columns]
    env = VecMonitor(DummyVecEnv([lambda: TradingEnv(df)]))

    model = DQN(
        "MlpPolicy", env,
        learning_rate=1e-4,
        buffer_size=50000,
        learning_starts=1000,
        batch_size=64,
        gamma=0.99,
        train_freq=4,
        target_update_interval=1000,
        exploration_fraction=0.2,
        seed=42,
        verbose=1,
    )
    model.learn(total_timesteps=args.timesteps)
    out = Path(args.out_dir) / f"dqn_v{args.version}.zip"
    model.save(str(out))
    print(f"[OK] DQN saved -> {out}")


if __name__ == "__main__":
    main()
