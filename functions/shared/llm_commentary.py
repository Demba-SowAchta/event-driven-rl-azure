"""
Bonus 4 - LLM market commentary via Hugging Face Inference API.

Apres chaque episode, genere un commentaire en langage naturel:
  Ex: "L'agent a realise +19% en 2024 avec un Sharpe de 1.42, principalement
       via 78 positions longues durant le Q3."

Le worker importe ce module et appelle market_commentary() avant l'upsert Cosmos.
"""
import logging, os, requests

HF_TOKEN = os.environ.get("HUGGINGFACE_TOKEN", "")
HF_MODEL = os.environ.get("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.2")
HF_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"


def market_commentary(episode_doc: dict) -> str | None:
    """Retourne un commentaire 1 phrase. None si pas de token / echec."""
    if not HF_TOKEN:
        return None
    prompt = (
        f"[INST] You are a financial analyst. In ONE sentence (max 30 words), "
        f"summarize this trading agent backtest. "
        f"File: {episode_doc['blob_name']}, "
        f"Algorithm: {episode_doc['algo']}, "
        f"Cumulative return: {episode_doc['cumulative_return']*100:.2f}%, "
        f"Sharpe: {episode_doc['sharpe_ratio']:.2f}, "
        f"Max drawdown: {episode_doc['max_drawdown']*100:.2f}%, "
        f"Actions: {episode_doc['n_buy']} BUY / {episode_doc['n_hold']} HOLD / "
        f"{episode_doc['n_sell']} SELL. [/INST]"
    )
    try:
        resp = requests.post(
            HF_URL, headers={"Authorization": f"Bearer {HF_TOKEN}"},
            json={"inputs": prompt, "parameters": {"max_new_tokens": 80}},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data[0]["generated_text"] if isinstance(data, list) else str(data)
        return text.replace(prompt, "").strip().split("\n")[0]
    except Exception as exc:
        logging.warning("LLM commentary failed: %s", exc)
        return None
