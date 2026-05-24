import os
import re
import json
import logging
from groq import Groq

logger = logging.getLogger(__name__)
MODEL = "llama-3.3-70b-versatile"
EMOJI = {"POSITIVO": "✅", "NEUTRO": "⚠️", "NEGATIVO": "🔴"}

ORIGEM_LABEL = {
    "alpha_vantage": "Alpha Vantage",
    "reddit":        "Reddit",
    "google_news":   "Google News",
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
    """Retorna ate 5 noticias com rotulo de origem para o prompt do Groq."""
    items = noticias.get(ticker, [])[:5]
    return [
        "[{}] {}".format(ORIGEM_LABEL.get(n.get("origem", ""), "Web"), n["titulo"])
        for n in items
        if n.get("titulo")
    ]


def analisar_mercado(nome, cotacoes_mercado, noticias):
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    dados_prompt = [
        {"ticker": t, "noticias": _formatar_noticias(t, noticias)}
        for t in cotacoes_mercado
    ]

    if not any(d["noticias"] for d in dados_prompt):
        return {
            t: {"sentimento": "⚠️", "top_noticias": [], "resumo": "Sem noticias."}
            for t in cotacoes_mercado
        }

    prompt = (
        "Voce e um analista financeiro senior. Analise as noticias para cada ativo do mercado {}.\n"
        "As noticias vem de Alpha Vantage, Reddit e Google News - considere a fonte ao avaliar.\n\n"
        "Para cada ticker retorne:\n"
        "- sentimento: POSITIVO, NEUTRO ou NEGATIVO\n"
        "- top_noticias: os 3 titulos mais relevantes (sem o prefixo de fonte)\n"
        "- resumo: uma frase objetiva em portugues\n\n"
        "Dados:\n{}\n\n"
        "Responda APENAS com JSON valido:\n"
        '{{"TICKER": {{"sentimento": "...", "top_noticias": [...], "resumo": "..."}}, ...}}'
    ).format(nome, json.dumps(dados_prompt, ensure_ascii=False))

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2048,
        )
        dados = _extrair_json(resp.choices[0].message.content)

        resultado = {}
        for ticker in cotacoes_mercado:
            if ticker in dados:
                sent = dados[ticker].get("sentimento", "NEUTRO")
                resultado[ticker] = {
                    "sentimento": EMOJI.get(sent, "⚠️"),
                    "top_noticias": dados[ticker].get("top_noticias", [])[:3],
                    "resumo": dados[ticker].get("resumo", ""),
                }
            else:
                tits = [n["titulo"] for n in noticias.get(ticker, [])[:3]]
                resultado[ticker] = {
                    "sentimento": "⚠️",
                    "top_noticias": tits,
                    "resumo": "Analise nao disponivel.",
                }
        return resultado

    except Exception as exc:
        logger.error("Erro Groq (%s): %s", nome, exc)
        return {
            t: {
                "sentimento": "⚠️",
                "top_noticias": [n["titulo"] for n in noticias.get(t, [])[:3]],
                "resumo": "Erro na analise.",
            }
            for t in cotacoes_mercado
        }


def analisar_portfolio(cotacoes, noticias):
    resultado = {}
    for mercado, ativos in cotacoes.items():
        logger.info("Analisando mercado: %s", mercado)
        resultado[mercado] = analisar_mercado(mercado, ativos, noticias)
    return resultado


def gerar_resumo_geral(cotacoes):
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    linhas = [
        "{}: {:+.2f}%".format(ticker, d["variacao"])
        for ativos in cotacoes.values()
        for ticker, d in ativos.items()
        if d.get("variacao") is not None
    ]
    if not linhas:
        return "Nao foi possivel gerar o resumo do dia."
    prompt = (
        "Com base nas variacoes abaixo, escreva um resumo financeiro do dia em 2-3 frases em portugues.\n"
        "Destaque os maiores ganhos e perdas. Seja direto.\n\n"
        + "\n".join(linhas)
    )
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=250,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("Erro resumo geral: %s", exc)
        return "Nao foi possivel gerar o resumo do dia."