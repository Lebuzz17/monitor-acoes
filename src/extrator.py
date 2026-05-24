"""
extrator.py - extracao de conteudo completo de artigos em 4 camadas.

Prioridade por artigo:
  1. NewsAPI /everything  (content > 200 palavras, api key NEWS_API_KEY)
  2. BeautifulSoup        (requests + parse HTML, fallback se NewsAPI falhar)
  3. Firecrawl            (JS-heavy / paywalls parciais, api key FIRECRAWL_KEY)
  4. Fallback             (titulo + resumo RSS, marcado com [resumo])

Controle Firecrawl:
  - Contador mensal em logs/firecrawl_usage.log (JSON: {mes, count})
  - Desativa automaticamente quando count >= 450 no mes corrente
  - Budget por run: max 10 chamadas (evita queimar cota diaria toda)
  - Reset automatico no 1o dia de cada mes
"""

import os
import re
import json
import logging
import requests
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
FIRECRAWL_LOG = ROOT / "logs" / "firecrawl_usage.log"

MIN_PALAVRAS   = 200
MAX_PALAVRAS   = 800   # palavras armazenadas por artigo
GROQ_PALAVRAS  = 300   # palavras enviadas ao Groq por artigo
FIRECRAWL_LIMITE_MENSAL = 450
FIRECRAWL_LIMITE_RUN    = 10

DOMINIOS_NOTICIAS = (
    "bloomberg.com,reuters.com,apnews.com,ft.com,"
    "cnbc.com,marketwatch.com,seekingalpha.com,barrons.com,wsj.com,"
    "infomoney.com.br,braziljournal.com,moneytimes.com.br,"
    "valor.com.br,exame.com,estadao.com.br,broadcast.com.br"
)

# ─── Estatisticas da sessao ───────────────────────────────────────────────────
_stats = {"newsapi": 0, "beautifulsoup": 0, "firecrawl": 0, "fallback": 0}
_fc_run_count = 0


def reset_stats():
    global _stats, _fc_run_count
    _stats = {"newsapi": 0, "beautifulsoup": 0, "firecrawl": 0, "fallback": 0}
    _fc_run_count = 0


def get_stats():
    return dict(_stats)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _contar_palavras(texto):
    return len(texto.split()) if texto else 0


def _truncar(texto, max_p=MAX_PALAVRAS):
    if not texto:
        return ""
    palavras = texto.split()
    if len(palavras) <= max_p:
        return texto
    return " ".join(palavras[:max_p]) + "…"


def _limpar_html(texto):
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


# ─── Contador Firecrawl ───────────────────────────────────────────────────────

def _ler_contador_fc():
    mes = datetime.now().strftime("%Y-%m")
    try:
        if FIRECRAWL_LOG.exists():
            data = json.loads(FIRECRAWL_LOG.read_text())
            if data.get("mes") == mes:
                return int(data.get("count", 0))
    except Exception:
        pass
    return 0


def _incrementar_contador_fc():
    mes = datetime.now().strftime("%Y-%m")
    count = _ler_contador_fc() + 1
    try:
        FIRECRAWL_LOG.parent.mkdir(parents=True, exist_ok=True)
        FIRECRAWL_LOG.write_text(json.dumps({"mes": mes, "count": count}))
    except Exception as exc:
        logger.warning("Erro ao salvar contador FC: %s", exc)
    return count


def get_firecrawl_usage():
    """Retorna (count_mensal, limite_mensal) para exibicao."""
    return _ler_contador_fc(), FIRECRAWL_LIMITE_MENSAL


# ─── Camada 1: NewsAPI ────────────────────────────────────────────────────────

def _via_newsapi(titulo, link):
    api_key = os.getenv("NEWS_API_KEY", "")
    if not api_key:
        return None
    try:
        from newsapi import NewsApiClient
        client = NewsApiClient(api_key=api_key)

        # Busca por palavras-chave do titulo
        query = " ".join(titulo.split()[:6])
        resultado = client.get_everything(
            q=query,
            domains=DOMINIOS_NOTICIAS,
            sort_by="relevancy",
            page_size=5,
            language="en",
        )

        for art in resultado.get("articles", []):
            content = art.get("content", "") or ""
            # Free tier trunca com "[+N chars]" — detectar e ignorar
            if "[+" in content and "chars]" in content:
                continue
            if _contar_palavras(content) >= MIN_PALAVRAS:
                logger.debug("NewsAPI OK: %s", titulo[:50])
                return _truncar(content)
        return None

    except Exception as exc:
        logger.debug("NewsAPI erro: %s", str(exc)[:80])
        return None


# ─── Camada 2: BeautifulSoup ──────────────────────────────────────────────────

_BS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.google.com/",
}

_BS_SELECTORS = [
    "article",
    "main",
    "[role='main']",
    ".article-body",
    ".article__body",
    ".post-content",
    ".entry-content",
    ".story-body",
    ".content__body",
    "#article-body",
    "#story-body",
    ".article-content",
]

_BS_SKIP_DOMAINS = {"reddit.com", "google.com", "twitter.com", "t.co"}


def _via_beautifulsoup(link):
    if not link:
        return None
    # Pular dominios que nao fazem sentido scraping direto
    for dom in _BS_SKIP_DOMAINS:
        if dom in link:
            return None
    try:
        from bs4 import BeautifulSoup

        resp = requests.get(link, headers=_BS_HEADERS, timeout=8, allow_redirects=True)
        if resp.status_code != 200:
            return None

        # Sinal de paywall/login — desistir cedo
        url_final = resp.url.lower()
        if any(s in url_final for s in ["login", "signin", "subscribe", "paywall", "register"]):
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Remover ruido
        for tag in soup.find_all(["nav", "footer", "header", "aside", "script",
                                   "style", "noscript", "iframe", "form", "figure"]):
            tag.decompose()

        texto = ""

        # Tentar seletores semanticos
        for selector in _BS_SELECTORS:
            elem = soup.select_one(selector)
            if elem:
                t = _limpar_html(elem.get_text(separator=" ", strip=True))
                if _contar_palavras(t) >= MIN_PALAVRAS:
                    texto = t
                    break

        # Fallback: maior div
        if _contar_palavras(texto) < MIN_PALAVRAS:
            divs = soup.find_all("div")
            if divs:
                maior = max(divs, key=lambda d: len(d.get_text()))
                texto = _limpar_html(maior.get_text(separator=" ", strip=True))

        if _contar_palavras(texto) >= MIN_PALAVRAS:
            logger.debug("BS OK: %s", link[:60])
            return _truncar(texto)
        return None

    except Exception as exc:
        logger.debug("BS erro %s: %s", link[:50], str(exc)[:60])
        return None


# ─── Camada 3: Firecrawl ──────────────────────────────────────────────────────

def _via_firecrawl(link):
    global _fc_run_count
    if not link:
        return None

    api_key = os.getenv("FIRECRAWL_KEY", "")
    if not api_key:
        return None

    # Verificar limite mensal
    count_mensal = _ler_contador_fc()
    if count_mensal >= FIRECRAWL_LIMITE_MENSAL:
        logger.warning("Firecrawl desativado: limite mensal %d/%d", count_mensal, FIRECRAWL_LIMITE_MENSAL)
        return None

    # Verificar budget por run
    if _fc_run_count >= FIRECRAWL_LIMITE_RUN:
        logger.debug("Firecrawl: budget por run atingido (%d)", FIRECRAWL_LIMITE_RUN)
        return None

    try:
        from firecrawl import FirecrawlApp
        app = FirecrawlApp(api_key=api_key)

        result = app.scrape_url(link, formats=["markdown"])

        # Suporte a ScrapeResponse (v4.x) e dict (versoes anteriores)
        if hasattr(result, "markdown"):
            content = result.markdown or ""
        elif isinstance(result, dict):
            content = result.get("markdown", "") or ""
        else:
            content = str(result)

        _fc_run_count += 1
        novo_count = _incrementar_contador_fc()
        logger.info("Firecrawl: %d/run, %d/%d mensal", _fc_run_count, novo_count, FIRECRAWL_LIMITE_MENSAL)

        if _contar_palavras(content) >= MIN_PALAVRAS:
            return _truncar(content)
        return None

    except Exception as exc:
        logger.debug("Firecrawl erro %s: %s", link[:50], str(exc)[:80])
        return None


# ─── API publica ──────────────────────────────────────────────────────────────

def extrair_conteudo(noticia, ticker):
    """
    Tenta extrair conteudo completo em 4 camadas.
    Retorna (conteudo_str, fonte_str).
    fonte_str: "newsapi" | "beautifulsoup" | "firecrawl" | "fallback"
    """
    titulo = noticia.get("titulo", "")
    link   = noticia.get("link", "")
    resumo = noticia.get("resumo", "") or ""

    if not link:
        _stats["fallback"] += 1
        return "[resumo] " + titulo, "fallback"

    # Camada 1: NewsAPI
    c = _via_newsapi(titulo, link)
    if c:
        _stats["newsapi"] += 1
        return c, "newsapi"

    # Camada 2: BeautifulSoup
    c = _via_beautifulsoup(link)
    if c:
        _stats["beautifulsoup"] += 1
        return c, "beautifulsoup"

    # Camada 3: Firecrawl
    c = _via_firecrawl(link)
    if c:
        _stats["firecrawl"] += 1
        return c, "firecrawl"

    # Camada 4: Fallback
    _stats["fallback"] += 1
    texto = titulo + (" — " + resumo if resumo else "")
    return "[resumo] " + texto, "fallback"


def truncar_para_groq(conteudo, max_palavras=GROQ_PALAVRAS):
    """Trunca conteudo para o tamanho adequado ao prompt Groq."""
    if not conteudo:
        return conteudo
    palavras = conteudo.split()
    if len(palavras) <= max_palavras:
        return conteudo
    return " ".join(palavras[:max_palavras]) + "…"