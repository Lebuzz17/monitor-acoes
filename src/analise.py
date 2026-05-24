"""
analise.py - analise de sentimento e geracao de alertas/contexto via Groq LLaMA.

Exporta:
  gerar_alertas(cotacoes, noticias) -> dict
    {mercado: [{ticker, texto}]}
    Candidatos: |variacao| >= 1.0%. Groq filtra para >= 1.5% ou news negativas.
    Tickers sem noticias recentes (lista vazia) sao ignorados pelo Groq.

  gerar_contexto_macro(noticias_macro) -> str
    2 frases de contexto macro baseadas APENAS nas noticias fornecidas.
    Retorna "" se sem noticias.
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
    "macro_feed":    "Macro Feed",
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
            news_list = _formatar_noticias(ticker, noticias)
            if not news_list:
                logger.info("Sem noticias recentes para %s — alerta omitido", ticker)
                continue
            dados_prompt.append({
                "ticker":       ticker,
                "variacao_pct": round(d["variacao"], 2),
                "noticias":     news_list,
            })

        if not dados_prompt:
            logger.info("Alertas %s: candidatos sem noticias recentes, nenhum alerta", mercado)
            resultado[mercado] = []
            continue

        prompt = (
            "Voce e um analista financeiro senior. Para cada ativo abaixo com variacao >= 1%, "
            "escreva um alerta em 2-3 frases em portugues explicando o movimento e seu contexto.\n\n"
            "REGRAS IMPORTANTES:\n"
            "- Inclua APENAS ativos com variacao >= 1.5% OU com noticias negativas impactantes\n"
            "- Se a lista 'noticias' de um ativo estiver vazia, NAO gere alerta para ele\n"
            "- Nao invente informacoes que nao estejam nas noticias fornecidas\n"
            "- Use o ticker exato, mencione o percentual e a causa principal\n\n"
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


def gerar_contexto_macro(noticias_macro):
    """
    Gera 2 frases de contexto macro baseadas APENAS nas noticias fornecidas.
    Retorna string vazia se sem noticias suficientes.
    """
    if not noticias_macro:
        logger.info("Contexto macro: sem noticias disponiveis (filtro 48h)")
        return ""

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    titulos = [
        "[{}] {}".format(n.get("fonte", "web"), n.get("titulo", ""))
        for n in noticias_macro[:8]
        if n.get("titulo")
    ]

    if not titulos:
        return ""

    prompt = (
        "Com base APENAS nas seguintes noticias macroeconômicas recentes, "
        "redija exatamente 2 frases de contexto macro relevantes para um investidor brasileiro. "
        "Nao invente informacoes que nao estejam explicitamente nas noticias abaixo. "
        "Se as noticias nao permitirem um comentario util e embasado, "
        "responda apenas: Dados insuficientes para contexto macro.\n\n"
        "Noticias disponíveis:\n{}"
    ).format("\n".join("- " + t for t in titulos))

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=220,
        )
        texto = resp.choices[0].message.content.strip()
        logger.info("Contexto macro gerado: %d chars", len(texto))
        return texto
    except Exception as exc:
        logger.error("Erro Groq contexto macro: %s", exc)
        return ""