"""
RL inference service.

L'API charge le modele une seule fois au demarrage (singleton `rl_service`)
puis chaque appel a /predict ouvre un episode dans TradingEnv et rejoue
les actions pas a pas.

Pourquoi un singleton et pas un chargement par requete ?
  - joblib.load coute ~200ms et la cold-start de Container Apps suffit
  - garder le modele en RAM evite des I/O disque a chaque /predict
  - thread-safe car FastAPI route une requete a la fois par worker

StubAgent est utilise en CI pour tester sans installer torch (700MB).
Il prend une action 'HOLD' systematique, ce qui suffit pour valider
le pipeline I/O sans toucher au comportement RL.
"""
from __future__ import annotations

import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .config import settings
from .trading_env import TradingEnv


# Mapping action discrete -> label humain.
# Cohérent avec le training (model/train.py): 0=SELL, 1=HOLD, 2=BUY.
ACTION_LABELS = {0: "SELL", 1: "HOLD", 2: "BUY"}


class StubAgent:
    """
    Agent factice utilise en CI quand torch n'est pas installe.

    Renvoie toujours 'HOLD' (action=1). Suffisant pour verifier
    que l'API repond, que les tests passent et que Docker build marche.
    """

    def predict(self, obs, deterministic=True):
        if obs.ndim == 1:
            return 1, None
        return np.ones(obs.shape[0], dtype=np.int64), None


class RLService:
    """
    Singleton qui detient le modele PPO + meta-info.

    Cycle de vie:
        __init__()  -> attributs a None
        load()      -> appele une fois par le lifespan FastAPI
        run_episode() -> appele a chaque /predict
    """

    def __init__(self):
        self.agent = None
        self.algo: str = settings.algo
        self.framework: str = settings.framework
        self.agent_version: str = settings.model_version
        self.load_time_ms: float = 0.0

    # ------------------------------------------------------------------
    def load(self) -> None:
        """
        Charge le pickle joblib depuis MODEL_PATH.

        En CI le fichier est un StubAgent picklise. En prod c'est un
        objet PPO de stable-baselines3. Le code ne change pas car
        StubAgent expose la meme methode .predict() que PPO.
        """
        path = Path(settings.model_path)
        if not path.exists():
            raise FileNotFoundError(f"Model not found at {path}")

        t0 = time.perf_counter()
        self.agent = joblib.load(path)
        self.load_time_ms = (time.perf_counter() - t0) * 1000.0

    # ------------------------------------------------------------------
    def run_episode(self, rows: list[dict], initial_cash: float = 10_000.0) -> dict:
        """
        Rejoue un episode complet dans TradingEnv et calcule les metriques.

        Parametres
        ----------
        rows : list[dict]
            Liste de chandelles OHLCV. Validee par Pydantic en amont.
        initial_cash : float
            Capital de depart (defaut 10k$).

        Retour
        ------
        dict
            Tous les champs attendus par PredictResponse:
            actions[], labels[], rewards[], equity_curve[], total_reward,
            final_equity, cumulative_return, sharpe_ratio, max_drawdown,
            win_rate, n_buy, n_hold, n_sell, n_steps, agent_version,
            algo, duration_ms.
        """
        if self.agent is None:
            raise RuntimeError("Agent not loaded - call load() first")

        t0 = time.perf_counter()

        # Construire un DataFrame attendu par TradingEnv.
        df = pd.DataFrame(rows)[["Open", "High", "Low", "Close", "Volume"]]
        env = TradingEnv(df, initial_cash=initial_cash)
        obs, _ = env.reset()

        actions: list[int] = []
        rewards: list[float] = []
        equity_curve: list[float] = [env.equity]

        # Rollout deterministe. On reste sur un seul thread (FastAPI route
        # une requete a la fois par worker uvicorn).
        while True:
            action, _ = self.agent.predict(obs, deterministic=True)
            action_int = int(action)
            obs, reward, terminated, truncated, _ = env.step(action_int)
            actions.append(action_int)
            rewards.append(float(reward))
            equity_curve.append(float(env.equity))
            if terminated or truncated:
                break

        labels = [ACTION_LABELS[a] for a in actions]

        # ---- Metriques de performance ---------------------------------
        n_steps = len(actions)
        final_equity = equity_curve[-1]
        total_reward = float(sum(rewards))
        cumulative_return = (final_equity - initial_cash) / initial_cash

        # Sharpe ratio annualise (252 jours boursiers).
        # log-returns -> moyenne / std * sqrt(252). On clip a 0 si std nulle.
        if len(rewards) > 1 and np.std(rewards) > 1e-9:
            sharpe = float(np.mean(rewards) / np.std(rewards) * np.sqrt(252))
        else:
            sharpe = 0.0

        # Max drawdown: chute maximale depuis le plus haut precedent.
        eq_arr = np.array(equity_curve)
        running_max = np.maximum.accumulate(eq_arr)
        drawdowns = (eq_arr - running_max) / running_max
        max_drawdown = float(abs(drawdowns.min())) if len(drawdowns) else 0.0

        # Win rate = % d'etapes ou le reward log etait positif.
        win_rate = float(sum(1 for r in rewards if r > 0) / n_steps) if n_steps else 0.0

        # Comptage actions
        n_buy = sum(1 for a in actions if a == 2)
        n_hold = sum(1 for a in actions if a == 1)
        n_sell = sum(1 for a in actions if a == 0)

        duration_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "actions": actions,
            "labels": labels,
            "rewards": rewards,
            "equity_curve": equity_curve,
            "total_reward": total_reward,
            "final_equity": final_equity,
            "cumulative_return": cumulative_return,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_drawdown,
            "win_rate": win_rate,
            "n_buy": n_buy,
            "n_hold": n_hold,
            "n_sell": n_sell,
            "n_steps": n_steps,
            "agent_version": self.agent_version,
            "algo": self.algo,
            "duration_ms": duration_ms,
        }


# Singleton importe par main.py et par les tests.
rl_service = RLService()
