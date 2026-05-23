import os
import re
import json
import logging
from groq import Groq

logger = logging.getLogger(__name__)
MODEL = "llama-3.3-70b-versatile"
EMOJI = {"POSITIVO": "✅", "NEUTRO": "⚠️", "NEGATIVO": "🔴"}


def _extrair_json(texto: str) -> dict:
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def analisar_mercado(nome: str, cotacoes_mercado: dict, noticias: dict) -> dict:
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    dados_prompt = []
    for ticker, _ in cotacoes_mercado.items():
        titulos = [n["titulo"] for n in noticias.get(ticker, [])[:4] if n.get("titulo")]
        dados_prompt.append({"ticker": ticker, "noticias": titulos})

    if not any(d["noticias"] for d in dados_prompt):
        return {
            t: {"sentimento": "⚠️", "top_noticias": [], "resumo": "Sem noticias."}
            for t in cotacoes_mercado
        }

    prompt = (
        f"Voce e um analista financeiro. Analise as noticias para cada ativo do mercado {nome}.\n\n"
        "Para cada ticker retorne:\n"
        '- sentimento: "POSITIVO", "NEUTRO" ou "NEGATIVO"\n'
        "- top_noticias: lista com os 3 titulos mais relevantes\n"
        "- resumo: uma frase em portugues\n\n"
        f"Dados:\n{json.dumps(dados_prompt, ensure_ascii=False)}\n\n"
        "Responda APENAS com JSON valido, sem texto adicional:\n"
        '{"TICKER": {"sentimento": "...", "top_noticias": [...], "resumo": "..."}, ...}'
    )

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


def analisar_portfolio(cotacoes: dict, noticias: dict) -> dict:
    resultado = {}
    for mercado, ativos in cotacoes.items():
        logger.info("Analisando mercado: %s", mercado)
        resultado[mercado] = analisar_mercado(mercado, ativos, noticias)
    return resultado


def gerar_resumo_geral(cotacoes: dict) -> str:
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    linhas = []
    for ativos in cotacoes.values():
        for ticker, d in ativos.items():
            if d.get("variacao") is not None:
                linhas.append(f"{ticker}: {d['variacao']:+.2f}%")

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
