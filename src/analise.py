"""
analise.py - analise de sentimento e geracao de alertas via Groq LLaMA.

Exporta:
  gerar_alertas(cotacoes, noticias) -> dict
    {mercado: [{ticker, texto}]}
    - candidatos: tickers com abs(variacao) >= 1.0%
    - Groq filtra e escreve alertas de 2-3 frases para os mais relevantes
"""

import os
import re
import json
import logging
from groq import Groq

logger = logging.getLogger(__name__)
MODEL = "llama-3.3-70b-versatile"

ORIGEM_LABEL = {
    "alpha_vantage": "Alpha Vantage",
    "reddit":        "Reddit",
    "google_news":   "Google News",
    "seeking_alpha": "Seeking Alpha",
    "feed_br":       "Feed BR",
}


def _extrair_json(texto):
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def _formatar_noticias(ticker, noticias):
    """Retorna ate 4 noticias com rotulo de origem para o prompt do Groq."""
    items = noticias.get(ticker, [])[:4]
    return [
        "[{}] {}".format(ORIGEM_LABEL.get(n.get("origem", ""), "Web"), n["titulo"])
        for n in items
        if n.get("titulo")
    ]


def gerar_alertas(cotacoes, noticias):
    """
    Identifica tickers com movimentos relevantes e gera alertas textuais.
    Faz 2 chamadas ao Groq (uma por mercado).
    Retorna {mercado: [{ticker, texto}]}.
    """
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    resultado = {}

    for mercado, ativos in cotacoes.items():
        candidatos = {
            t: d for t, d in ativos.items()
            if d.get("variacao") is not None and abs(d["variacao"]) >= 1.0
        }

        if not candidatos:
            logger.info("Alertas %s: nenhum candidato (todos < 1%%)", mercado)
            resultado[mercado] = []
            continue

        dados_prompt = []
        for ticker, d in candidatos.items():
            dados_prompt.append({
                "ticker":      ticker,
                "variacao_pct": round(d["variacao"], 2),
                "noticias":    _formatar_noticias(ticker, noticias),
            })

        prompt = (
            "Voce e um analista financeiro senior. Para cada ativo abaixo com variacao >= 1%, "
            "escreva um alerta em 2-3 frases em portugues explicando o movimento do dia e seu contexto.\n"
            "Inclua apenas ativos com movimentos realmente relevantes (>= 1.5% ou com noticias negativas impactantes).\n"
            "Seja direto, use o ticker exato, mencione o valor percentual e a causa principal.\n\n"
            "Mercado: {}\n"
            "Candidatos:\n{}\n\n"
            "Responda APENAS com JSON valido, sem markdown:\n"
            "{{\"alertas\": [{{\"ticker\": \"...\", \"texto\": \"...\"}}]}}"
        ).format(mercado, json.dumps(dados_prompt, ensure_ascii=False))

        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1200,
            )
            dados_resp = _extrair_json(resp.choices[0].message.content)
            alertas = dados_resp.get("alertas", [])
            valid = [
                a for a in alertas
                if isinstance(a, dict) and a.get("ticker") and a.get("texto")
            ]
            resultado[mercado] = valid
            logger.info("Alertas %s: %d gerados de %d candidatos", mercado, len(valid), len(candidatos))
        except Exception as exc:
            logger.error("Erro Groq alertas (%s): %s", mercado, exc)
            resultado[mercado] = []

    return resultado