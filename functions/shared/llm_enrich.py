"""
Bonus 4 - LLM Market Commentary via Hugging Face.

Apres chaque episode, genere un commentaire marche en langage naturel.
Si HUGGINGFACE_TOKEN absent, retourne None silencieusement.
"""
import logging, os
import requests

HF_TOKEN = os.environ.get("HUGGINGFACE_TOKEN", "")
HF_MODEL = os.environ.get("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.2")
HF_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"


def enrich_commentary(episode_doc):
    """Genere une analyse 30 mots de l'episode RL."""
    if not HF_TOKEN:
        return None
    ret = episode_doc.get("cumulative_return", 0) * 100
    sharpe = episode_doc.get("sharpe_ratio", 0)
    nbuy = episode_doc.get("n_buy", 0)
    nsell = episode_doc.get("n_sell", 0)
    drawdown = episode_doc.get("max_drawdown", 0) * 100
    prompt = (
        f"[INST] You are a financial analyst. Write ONE short professional sentence "
        f"(max 30 words) summarizing this RL trading episode. "
        f"Cumulative return: {ret:+.1f}%, Sharpe: {sharpe:.2f}, "
        f"BUY signals: {nbuy}, SELL signals: {nsell}, "
        f"Max drawdown: {drawdown:.1f}%. [/INST]"
    )
    try:
        resp = requests.post(HF_URL,
            headers={"Authorization": f"Bearer {HF_TOKEN}"},
            json={"inputs": prompt, "parameters": {"max_new_tokens": 80}},
            timeout=15)
        resp.raise_for_status()
        data = resp.json()
        text = data[0]["generated_text"] if isinstance(data, list) else str(data)
        return text.replace(prompt, "").strip().split("\n")[0]
    except Exception as exc:
        logging.warning("LLM commentary failed: %s", exc)
        return None
