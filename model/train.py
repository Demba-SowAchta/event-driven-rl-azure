"""
Entrainement PPO sur le TradingEnv.

Usage:
    python train.py --version 1.0.0 --timesteps 100000

Reproductibilite:
  - seed fixe 42
  - pinned requirements.txt
  - dataset versionne (SPY)
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# stable_baselines3 et torch sont des dependances "heavy"
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import EvalCallback
from stable_baselines3.common.vec_env import DummyVecEnv, VecMonitor

# Permet import trading_env quand on lance depuis n'importe ou
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_env import TradingEnv


RANDOM_SEED = 42


def make_env(csv_path: Path):
    df = pd.read_csv(csv_path, parse_dates=True, index_col=0)
    df.columns = [c.title() if c.title() in ("Open","High","Low","Close","Volume") else c for c in df.columns]
    def _fn():
        return TradingEnv(df)
    return _fn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, help="Semver, e.g. 1.0.0")
    parser.add_argument("--train-csv", default="data/spy_train.csv")
    parser.add_argument("--eval-csv",  default="data/spy_eval.csv")
    parser.add_argument("--timesteps", type=int, default=100_000)
    parser.add_argument("--out-dir",   default="artifacts")
    args = parser.parse_args()

    np.random.seed(RANDOM_SEED)

    train_csv = Path(args.train_csv)
    eval_csv = Path(args.eval_csv)
    out_dir = Path(args.out_dir); out_dir.mkdir(exist_ok=True, parents=True)

    # Vectorize for PPO (DummyVecEnv = single process, suffisant)
    train_env = VecMonitor(DummyVecEnv([make_env(train_csv)]))
    eval_env  = VecMonitor(DummyVecEnv([make_env(eval_csv)]))

    print(f"[INFO] Training PPO for {args.timesteps} timesteps...")
    model = PPO(
        "MlpPolicy", train_env,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        seed=RANDOM_SEED,
        verbose=1,
        tensorboard_log=str(out_dir / "tb_logs"),
    )

    eval_cb = EvalCallback(
        eval_env, best_model_save_path=str(out_dir / "best"),
        log_path=str(out_dir / "eval_logs"),
        eval_freq=5000, n_eval_episodes=3, deterministic=True,
    )

    model.learn(total_timesteps=args.timesteps, callback=eval_cb)

    model_path = out_dir / f"ppo_v{args.version}.zip"
    model.save(model_path)
    print(f"[OK] Model saved -> {model_path}")

    # Evaluate on eval set
    from eval import evaluate
    metrics = evaluate(str(model_path), str(eval_csv))
    metrics["agent_version"] = args.version
    metrics["random_seed"] = RANDOM_SEED
    metrics["algo"] = "PPO"
    metrics["framework"] = "stable-baselines3"
    metrics["timesteps"] = args.timesteps

    metrics_path = out_dir / f"metrics_v{args.version}.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[OK] Metrics saved -> {metrics_path}")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
