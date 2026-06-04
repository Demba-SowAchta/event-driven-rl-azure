"""
live_predict.py
---------------
Petit script pour tester l'API RL avec des donnees Yahoo Finance fraiches.

Usage rapide:
    python live_predict.py --url https://rl-api.xxx.azurecontainerapps.io --symbol SPY
    python live_predict.py --url http://localhost:8000 --symbol AAPL --interval 5m
    python live_predict.py --symbols SPY,AAPL,TSLA   # multi-actifs
    python live_predict.py --csv data/spy_2024.csv   # depuis un fichier local

Le script:
  1. recupere des bougies OHLCV depuis Yahoo Finance via yfinance
  2. les envoie en POST a /predict
  3. affiche les metriques (return, sharpe, drawdown) + courbe d'equity ASCII

Pourquoi yfinance et pas une API payante ?
  C'est un projet etudiant a budget zero. yfinance scrappe Yahoo Finance,
  c'est gratuit, c'est rate-limited mais largement suffisant pour une demo.
  Pour de la prod on passerait sur Polygon.io ou Alpaca.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime

import requests


# Couleurs ANSI - pas de lib externe necessaire
class C:
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"


def log(level: str, msg: str) -> None:
    """Logger one-liner avec timestamp."""
    ts = datetime.now().strftime("%H:%M:%S")
    colors = {"INFO": C.BLUE, "OK": C.GREEN, "WARN": C.YELLOW, "ERR": C.RED}
    print(f"{C.GRAY}{ts}{C.END} {colors.get(level, '')}{level:4s}{C.END}  {msg}")


# ---------------------------------------------------------------------------
# 1. Recuperation des donnees
# ---------------------------------------------------------------------------
def fetch_from_yahoo(symbol: str, interval: str, n_bars: int) -> list[dict]:
    """
    Telecharge n_bars chandelles depuis Yahoo Finance.

    Yahoo a des contraintes bizarres:
      - intraday (1m, 5m...) : historique max 7-60 jours
      - heures de marche US : 1m n'est dispo que pendant les sessions

    Si l'intervalle demande retourne moins que n_bars on retombe sur un
    intervalle plus large (5m -> 15m -> 1h -> 1d). Ca evite de planter
    quand le marche est ferme.
    """
    try:
        import yfinance as yf
    except ImportError:
        log("ERR", "yfinance not installed. Run: pip install yfinance")
        sys.exit(1)

    # Cascade de fallback - chaque interval a une periode max compatible
    chain = [
        (interval, "7d"),
        ("5m", "60d"),
        ("15m", "60d"),
        ("1h", "730d"),
        ("1d", "5y"),
    ]
    # dedup en gardant l'ordre
    seen = set()
    chain = [(i, p) for i, p in chain if not (i in seen or seen.add(i))]

    df = None
    used = interval
    for interv, period in chain:
        log("INFO", f"yfinance: {symbol} interval={interv} period={period}")
        try:
            df = yf.download(symbol, period=period, interval=interv,
                             progress=False, auto_adjust=False, threads=False)
        except Exception as exc:
            log("WARN", f"yfinance error on {interv}: {exc}")
            df = None
            continue
        if df is not None and len(df) >= n_bars:
            used = interv
            break

    if df is None or len(df) < n_bars:
        log("ERR", f"Could not fetch {n_bars} bars for {symbol}")
        sys.exit(2)

    if used != interval:
        log("WARN", f"Fell back from {interval} to {used} (market probably closed)")

    df = df.tail(n_bars).reset_index(drop=True)
    # yfinance retourne parfois un MultiIndex sur les colonnes pour un seul
    # symbole - on aplatit.
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "Open":   float(r["Open"]),
            "High":   float(r["High"]),
            "Low":    float(r["Low"]),
            "Close":  float(r["Close"]),
            "Volume": float(r["Volume"]) if "Volume" in r else 0.0,
        })
    log("OK", f"{len(rows)} bars fetched (last close={rows[-1]['Close']:.2f})")
    return rows


def fetch_from_csv(path: str) -> list[dict]:
    """Mode offline: lire un CSV au format Open,High,Low,Close,Volume."""
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: float(r[k]) for k in ("Open", "High", "Low", "Close", "Volume")})
    log("OK", f"{len(rows)} rows loaded from {path}")
    return rows


# ---------------------------------------------------------------------------
# 2. Appel API
# ---------------------------------------------------------------------------
def call_predict(api_url: str, rows: list[dict], initial_cash: float, timeout: float):
    url = api_url.rstrip("/") + "/predict"
    log("INFO", f"POST {url} ({len(rows)} bars)")
    t0 = time.perf_counter()
    resp = requests.post(url, json={"rows": rows, "initial_cash": initial_cash}, timeout=timeout)
    elapsed = (time.perf_counter() - t0) * 1000
    if resp.status_code != 200:
        log("ERR", f"HTTP {resp.status_code}: {resp.text[:200]}")
        resp.raise_for_status()
    log("OK", f"200 OK in {elapsed:.0f}ms (server reported {resp.json()['duration_ms']:.0f}ms)")
    return resp.json()


# ---------------------------------------------------------------------------
# 3. Affichage des resultats
# ---------------------------------------------------------------------------
def print_summary(symbol: str, result: dict) -> None:
    """Resume une page facile a lire dans le terminal."""
    ret_pct = result["cumulative_return"] * 100
    ret_color = C.GREEN if ret_pct >= 0 else C.RED
    sharpe = result["sharpe_ratio"]
    sharpe_color = C.GREEN if sharpe >= 1 else (C.YELLOW if sharpe >= 0 else C.RED)

    print()
    print(f"   {C.BOLD}{C.CYAN}{symbol}{C.END}   {C.DIM}agent={result['agent_version']} algo={result['algo']}{C.END}")
    print(f"   {C.GRAY}{'-'*54}{C.END}")
    print(f"   Cumulative return  {ret_color}{ret_pct:+7.2f}%{C.END}")
    print(f"   Sharpe ratio       {sharpe_color}{sharpe:7.2f}{C.END}")
    print(f"   Max drawdown       {C.RED}{result['max_drawdown']*100:7.2f}%{C.END}")
    print(f"   Win rate           {result['win_rate']*100:7.2f}%")
    print(f"   Final equity       ${result['final_equity']:,.2f}")
    print(f"   Actions:  {C.GREEN}BUY={result['n_buy']}{C.END}  "
          f"{C.GRAY}HOLD={result['n_hold']}{C.END}  "
          f"{C.RED}SELL={result['n_sell']}{C.END}  "
          f"({result['n_steps']} steps)")


def print_equity_chart(equity_curve: list[float], width: int = 60, height: int = 12) -> None:
    """Mini-chart ASCII de la courbe d'equity."""
    if len(equity_curve) < 2:
        return
    lo, hi = min(equity_curve), max(equity_curve)
    span = hi - lo or 1.0
    # downsample pour tenir dans `width` colonnes
    step = max(1, len(equity_curve) // width)
    sampled = equity_curve[::step][:width]
    print()
    print(f"   {C.DIM}equity curve  (${hi:,.0f} top, ${lo:,.0f} bottom){C.END}")
    for row in range(height, 0, -1):
        threshold = lo + (row / height) * span
        line = "   "
        for v in sampled:
            line += "#" if v >= threshold else " "
        print(C.GREEN + line + C.END)
    print(f"   {C.GRAY}{'-' * (len(sampled) + 1)}{C.END}")


# ---------------------------------------------------------------------------
# 4. Main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Test the RL trading API with real or local market data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--url", default="http://localhost:8000",
                   help="Base URL of the API (default: http://localhost:8000)")
    p.add_argument("--symbol", default="SPY",
                   help="Yahoo Finance ticker (default: SPY)")
    p.add_argument("--symbols", default=None,
                   help="Multi-asset run, comma-separated, e.g. SPY,AAPL,TSLA")
    p.add_argument("--interval", default="1d",
                   choices=["1m", "5m", "15m", "30m", "1h", "1d"],
                   help="Bar interval (default: 1d, auto-fallback if data missing)")
    p.add_argument("--n-bars", type=int, default=60,
                   help="Number of bars to send (min 10, recommend >= 50)")
    p.add_argument("--csv", default=None,
                   help="Read OHLCV from local CSV instead of Yahoo")
    p.add_argument("--initial-cash", type=float, default=10000.0,
                   help="Starting cash for the backtest (default: 10000)")
    p.add_argument("--timeout", type=float, default=120.0,
                   help="HTTP timeout in seconds (default: 120)")
    p.add_argument("--no-chart", action="store_true",
                   help="Skip the ASCII equity chart")
    p.add_argument("--json", action="store_true",
                   help="Print raw JSON response instead of pretty summary")
    return p.parse_args()


def run_one(args, symbol: str) -> int:
    rows = fetch_from_csv(args.csv) if args.csv else \
           fetch_from_yahoo(symbol, args.interval, args.n_bars)
    try:
        result = call_predict(args.url, rows, args.initial_cash, args.timeout)
    except requests.RequestException as exc:
        log("ERR", f"API call failed: {exc}")
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print_summary(symbol, result)
    if not args.no_chart:
        print_equity_chart(result["equity_curve"])
    return 0


def main() -> int:
    args = parse_args()
    symbols = [s.strip().upper() for s in (args.symbols or args.symbol).split(",")]

    # Verifier que l'API repond avant d'aller chercher Yahoo (ca evite de
    # gaspiller un appel Yahoo si on a tape la mauvaise URL).
    health_url = args.url.rstrip("/") + "/health"
    try:
        r = requests.get(health_url, timeout=10)
        if r.status_code == 200 and r.json().get("agent_loaded"):
            log("OK", f"API healthy ({health_url})")
        else:
            log("WARN", f"/health says: {r.status_code} {r.text[:100]}")
    except requests.RequestException as exc:
        log("ERR", f"Cannot reach API at {args.url}: {exc}")
        return 3

    for sym in symbols:
        run_one(args, sym)
    return 0


if __name__ == "__main__":
    sys.exit(main())
