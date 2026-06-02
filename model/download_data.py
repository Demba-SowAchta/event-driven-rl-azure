"""Telecharge les donnees Yahoo Finance pour entrainement & eval."""
import argparse
from pathlib import Path

import yfinance as yf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--train-start", default="2015-01-01")
    parser.add_argument("--train-end",   default="2023-12-31")
    parser.add_argument("--eval-start",  default="2024-01-01")
    parser.add_argument("--eval-end",    default="2024-12-31")
    parser.add_argument("--out-dir",     default="data")
    args = parser.parse_args()

    Path(args.out_dir).mkdir(exist_ok=True, parents=True)

    print(f"[INFO] Downloading {args.symbol} {args.train_start} -> {args.train_end}")
    train = yf.download(args.symbol, start=args.train_start, end=args.train_end,
                        auto_adjust=True, progress=False)
    train.to_csv(Path(args.out_dir) / f"{args.symbol.lower()}_train.csv")
    print(f"  -> {len(train)} rows")

    print(f"[INFO] Downloading {args.symbol} {args.eval_start} -> {args.eval_end}")
    test = yf.download(args.symbol, start=args.eval_start, end=args.eval_end,
                       auto_adjust=True, progress=False)
    test.to_csv(Path(args.out_dir) / f"{args.symbol.lower()}_eval.csv")
    print(f"  -> {len(test)} rows")

    print("[OK] Done")


if __name__ == "__main__":
    main()
