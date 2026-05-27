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

GROQ_PALAVRAS_ARTIGO = 300
GROQ_PALAVRAS_MACRO  = 200
TOKEN_LIMITE_TOTAL   = 4000
MAX_ARTIGOS_NORMAL   = 5
MAX_ARTIGOS_REDUCAO  = 3


def _extrair_json(texto):
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def _contar_palavras(texto):
    return len(texto.split()) if texto else 0


def _truncar(texto, max_palavras):
    palavras = texto.split()
    if len(palavras) <= max_palavras:
        return texto
    return " ".join(palavras[:max_palavras]) + "..."


def _formatar_noticias(ticker, noticias, max_artigos=MAX_ARTIGOS_NORMAL):
    """
    Retorna lista de dicts {fonte, conteudo, tipo} para o prompt do Groq.
    Se artigo tem conteudo completo (>= 200 palavras, sem [resumo]) usa-o truncado a 300 palavras.
    Caso contrario usa apenas o titulo.
    """
    items = noticias.get(ticker, [])[:max_artigos]
    resultado = []
    for n in items:
        if not n.get("titulo"):
            continue
        fonte = ORIGEM_LABEL.get(n.get("origem", ""), "Web")
        conteudo_raw = n.get("conteudo", "")
        is_resumo = "[resumo]" in conteudo_raw if conteudo_raw else True
        palavras = _contar_palavras(conteudo_raw)

        if conteudo_raw and not is_resumo and palavras >= 200:
            texto = _truncar(conteudo_raw, GROQ_PALAVRAS_ARTIGO)
            tipo = "conteudo_completo"
        else:
            texto = n["titulo"]
            tipo = "titulo_apenas"

        resultado.append({"fonte": fonte, "conteudo": texto, "tipo": tipo})
    return resultado


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
            news_list = _formatar_noticias(ticker, noticias, MAX_ARTIGOS_NORMAL)
            if not news_list:
                logger.info("Sem noticias recentes para %s - alerta omitido", ticker)
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

        total_palavras = sum(
            _contar_palavras(art["conteudo"])
            for item in dados_prompt
            for art in item["noticias"]
        )
        if total_palavras > TOKEN_LIMITE_TOTAL:
            logger.info("Alertas %s: total %d palavras > %d, reduzindo para %d artigos/ticker",
                        mercado, total_palavras, TOKEN_LIMITE_TOTAL, MAX_ARTIGOS_REDUCAO)
            dados_prompt = []
            for ticker, d in candidatos.items():
                news_list = _formatar_noticias(ticker, noticias, MAX_ARTIGOS_REDUCAO)
                if not news_list:
                    continue
                dados_prompt.append({
                    "ticker":       ticker,
                    "variacao_pct": round(d["variacao"], 2),
                    "noticias":     news_list,
                })

        tem_conteudo = any(
            art["tipo"] == "conteudo_completo"
            for item in dados_prompt
            for art in item["noticias"]
        )

        if tem_conteudo:
            instrucao_analise = (
                "Para cada ativo, as noticias podem conter o conteudo completo do artigo (tipo conteudo_completo) "
                "ou apenas o titulo (tipo titulo_apenas). "
                "Quando houver conteudo completo, faca uma analise detalhada em 3 pontos: "
                "(1) fato principal, (2) impacto esperado no ativo, (3) risco ou oportunidade. "
                "Quando houver apenas titulo, seja mais conciso (1-2 frases)."
            )
        else:
            instrucao_analise = (
                "As noticias disponiveis sao apenas titulos. "
                "Escreva um alerta conciso em 1-2 frases em portugues para cada ativo."
            )

        prompt = (
            "Voce e um analista financeiro senior. Para cada ativo abaixo com variacao >= 1%, "
            "escreva um alerta em portugues explicando o movimento e seu contexto.\n\n"
            "REGRAS IMPORTANTES:\n"
            "- Inclua APENAS ativos com variacao >= 1.5%% OU com noticias negativas impactantes\n"
            "- Se a lista noticias de um ativo estiver vazia, NAO gere alerta para ele\n"
            "- Nao invente informacoes que nao estejam nas noticias fornecidas\n"
            "- Use o ticker exato, mencione o percentual e a causa principal\n"
            "- {instrucao}\n\n"
            "Mercado: {mercado}\n"
            "Candidatos:\n{dados}\n\n"
            "Responda APENAS com JSON valido, sem markdown:\n"
            "{{\"alertas\": [{{\"ticker\": \"...\", \"texto\": \"...\"}}]}}"
        ).format(
            instrucao=instrucao_analise,
            mercado=mercado,
            dados=json.dumps(dados_prompt, ensure_ascii=False),
        )

        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1500,
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
    Usa conteudo completo quando disponivel (truncado a 200 palavras), senao titulo.
    Retorna string vazia se sem noticias suficientes.
    """
    if not noticias_macro:
        logger.info("Contexto macro: sem noticias disponiveis (filtro 48h)")
        return ""

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    itens_prompt = []
    for n in noticias_macro[:8]:
        if not n.get("titulo"):
            continue
        fonte = n.get("fonte", "web")
        conteudo_raw = n.get("conteudo", "")
        is_resumo = "[resumo]" in conteudo_raw if conteudo_raw else True
        palavras = _contar_palavras(conteudo_raw)

        if conteudo_raw and not is_resumo and palavras >= 200:
            texto = _truncar(conteudo_raw, GROQ_PALAVRAS_MACRO)
        else:
            texto = n.get("titulo", "")

        itens_prompt.append("[{}] {}".format(fonte, texto))

    if not itens_prompt:
        return ""

    prompt = (
        "Voce e um analista financeiro. Analise as noticias abaixo e escreva 1-2 frases "
        "de contexto de mercado para um investidor brasileiro, priorizando os temas: "
        "(1) mercados globais: S&P 500, Nasdaq, bolsas, volatilidade; "
        "(2) politica monetaria: Fed, juros, inflacao; "
        "(3) geopolitica: guerras, sancoes, tensoes; "
        "(4) commodities: petroleo, minerio, ouro; "
        "(5) eventos sobre o Brasil ou mercados emergentes. "
        "Use APENAS informacoes explicitas nas noticias fornecidas. "
        "Se nenhuma noticia tiver qualquer relevancia para mercados financeiros globais "
        "ou para o Brasil, responda apenas: Dados insuficientes para contexto macro.\n\n"
        "Noticias disponíveis:\n{}"
    ).format("\n".join("- " + t for t in itens_prompt))

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=280,
        )
        texto = resp.choices[0].message.content.strip()
        logger.info("Contexto macro gerado: %d chars", len(texto))
        return texto
    except Exception as exc:
        logger.error("Erro Groq contexto macro: %s", exc)
        return ""