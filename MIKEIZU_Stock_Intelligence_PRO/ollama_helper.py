"""Optional local Ollama qualitative assistance, never used as a trading signal."""
import requests


def summarize_locally(symbol: str, articles: list[dict], model: str = "llama3.2:3b") -> str:
    if not articles:
        return "No headlines available to summarize."
    numbered = "\n".join(f"[{i}] {x['title']} (published {x['published']}; {x['source']})"
                         for i, x in enumerate(articles[:12], 1))
    prompt = f"""You are a cautious investment-research assistant. Stock ticker: {symbol}.
Only these headlines are evidence; you CANNOT see the full articles or verify the claims:
{numbered}
Summarize in 180 words or less with: (1) bull case, (2) bear case, (3) dividend implications if any,
(4) what to verify before buying. Cite headline numbers [1], [2] for ALL factual claims.
Do not invent facts, financial figures, targets, current prices, dates, or guaranteed returns.
If evidence is missing, say so. Do NOT issue a direct buy/sell order."""
    response = requests.post("http://127.0.0.1:11434/api/generate",
                             json={"model": model, "prompt": prompt, "stream": False,
                                   "options": {"temperature": 0.15}}, timeout=(4, 90))
    response.raise_for_status()
    body = response.json()
    return str(body.get("response") or "No summary generated.")
