"""
noticias.py - coleta e ranqueamento de noticias de multiplas fontes.

Fontes:
  - Google News RSS  (todos os tickers)
  - Alpha Vantage    (americanos, 1 chamada batch, usa relevance_score proprio)
  - Reddit JSON API  (americanos: r/investing, r/stocks, r/ValueInvesting
                      brasileiros: r/investimentos, r/financas, filtra >= 10 upvotes)

Score de relevancia:
  score_av  base = relevance_score Alpha Vantage (0-5)
  +3  fonte confiavel (Reuters, Bloomberg, WSJ, Valor Economico, Infomoney...)
  +2  titulo menciona o ticker ou nome da empresa diretamente
  +2  noticia das ultimas 12h  |  +1 ultimas 24h
  deduplicacao por hash do titulo normalizado (60 chars)
  retorna top 5 por score_final
"""

import os
import re
import time
import logging
import hashlib
import urllib.parse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests
import feedparser

logger = logging.getLogger(__name__)

EMPRESA_MAP = {
    "AAPL":     "Apple",
    "UNH":      "UnitedHealth",
    "AMZN":     "Amazon",
    "GOOGL":    "Google Alphabet",
    "V":        "Visa",
    "MA":       "Mastercard",
    "MSFT":     "Microsoft",
    "JPM":      "JPMorgan",
    "BAC":      "Bank of America",
    "IVV":      "S&P 500 ETF",
    "QQQ":      "Nasdaq ETF",
    "GBTC":     "Bitcoin Grayscale",
    "EIMI.L":   "Emerging Markets ETF",
    "BBAS3.SA": "Banco do Brasil",
    "BOVA11.SA":"Ibovespa ETF",
    "ITUB4.SA": "Itau Unibanco",
    "VALE3.SA":  "Vale",
    "SMALL11.SA":"Small Cap Brasil",
    "PRIO3.SA":  "PetroRio",
}

FONTES_CONFIAVEIS = {
    "reuters", "bloomberg", "wsj", "wall street journal",
    "financial times", "ft.com", "cnbc", "marketwatch",
    "valor economico", "valor econômico", "infomoney",
    "exame invest", "money times", "investing.com",
}

SUBREDDITS_AMER = ["investing", "stocks", "ValueInvesting"]
SUBREDDITS_BRAS = ["investimentos", "financas"]

ORIGEM_LABEL = {
    "alpha_vantage": "Alpha Vantage",
    "reddit":        "Reddit",
    "google_news":   "Google News",
}


def _limpar_ticker(ticker):
    return ticker.replace(".SA", "").replace(".L", "")


def _parse_ts(raw):
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
    except Exception:
        pass
    try:
        if "T" in raw and len(raw) == 15:
            return datetime.strptime(raw, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _score_noticia(noticia, ticker):
    score = noticia.get("score_av", 0.0)

    fonte = noticia.get("fonte", "").lower()
    if any(f in fonte for f in FONTES_CONFIAVEIS):
        score += 3

    titulo = noticia.get("titulo", "").lower()
    ticker_clean = _limpar_ticker(ticker).lower()
    empresa = EMPRESA_MAP.get(ticker, "").lower()
    if ticker_clean in titulo or (empresa and empresa in titulo):
        score += 2

    ts = noticia.get("publicado_ts")
    if ts:
        horas = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        if horas <= 12:
            score += 2
        elif horas <= 24:
            score += 1

    return score


def _deduplicar(noticias):
    vistas = set()
    resultado = []
    for n in noticias:
        chave = re.sub(r"[^a-z0-9]", "", n.get("titulo", "").lower())[:60]
        h = hashlib.md5(chave.encode()).hexdigest()
        if h not in vistas:
            vistas.add(h)
            resultado.append(n)
    return resultado


def _google_news(ticker, max_itens=8):
    nome = _limpar_ticker(ticker)
    empresa = EMPRESA_MAP.get(ticker, "")
    termo = "{} {} stock".format(nome, empresa).strip() if empresa else "{} stock".format(nome)
    url = (
        "https://news.google.com/rss/search"
        "?q={}&hl=pt-BR&gl=BR&ceid=BR:pt-419".format(urllib.parse.quote(termo))
    )
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
        noticias = []
        for entry in feed.entries[:max_itens]:
            titulo = entry.get("title", "").strip()
            if not titulo:
                continue
            fonte = ""
            if " - " in titulo:
                titulo, fonte = titulo.rsplit(" - ", 1)
                titulo, fonte = titulo.strip(), fonte.strip()
            noticias.append({
                "titulo":       titulo,
                "fonte":        fonte,
                "link":         entry.get("link", ""),
                "publicado_ts": _parse_ts(entry.get("published", "")),
                "origem":       "google_news",
                "score_av":     0.0,
            })
        return noticias
    except Exception as exc:
        logger.error("Google News %s: %s", ticker, exc)
        return []


def _alpha_vantage_batch(tickers, max_itens=50):
    """
    Uma unica chamada de API para todos os tickers americanos.
    Retorna {ticker_original: [noticias]}.
    Free tier: 25 req/dia - batch evita estourar o limite.
    """
    api_key = os.getenv("ALPHA_VANTAGE_KEY", "")
    if not api_key or api_key.startswith("sua_"):
        logger.info("ALPHA_VANTAGE_KEY nao configurada, pulando Alpha Vantage")
        return {}

    limpos = [_limpar_ticker(t) for t in tickers]
    ticker_map = {_limpar_ticker(t): t for t in tickers}

    url = (
        "https://www.alphavantage.co/query"
        "?function=NEWS_SENTIMENT&tickers={}&apikey={}&limit={}".format(
            ",".join(limpos), api_key, max_itens
        )
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if "feed" not in data:
            aviso = data.get("Note", data.get("Information", str(data)))
            logger.warning("Alpha Vantage sem feed: %s", str(aviso)[:120])
            return {}

        resultado = {t: [] for t in tickers}
        for item in data["feed"]:
            ts = _parse_ts(item.get("time_published", ""))
            titulo = item.get("title", "").strip()
            if not titulo:
                continue
            for sent in item.get("ticker_sentiment", []):
                av_t = sent.get("ticker", "")
                original = ticker_map.get(av_t)
                if original is None:
                    continue
                try:
                    rel = float(sent.get("relevance_score", 0)) * 5
                except (ValueError, TypeError):
                    rel = 0.0
                if rel < 0.5:
                    continue
                resultado[original].append({
                    "titulo":       titulo,
                    "fonte":        item.get("source", ""),
                    "link":         item.get("url", ""),
                    "publicado_ts": ts,
                    "origem":       "alpha_vantage",
                    "score_av":     rel,
                })

        total = sum(len(v) for v in resultado.values())
        logger.info("Alpha Vantage: %d noticias para %d tickers", total, len(tickers))
        return resultado

    except Exception as exc:
        logger.error("Alpha Vantage batch: %s", exc)
        return {}


def _reddit(ticker, eh_americano=True, max_por_sub=5):
    """Busca posts com >= 10 upvotes nos subreddits relevantes."""
    ticker_clean = _limpar_ticker(ticker)
    empresa = EMPRESA_MAP.get(ticker, ticker_clean)
    query = urllib.parse.quote("{} {}".format(ticker_clean, empresa))
    subreddits = SUBREDDITS_AMER if eh_americano else SUBREDDITS_BRAS
    headers = {"User-Agent": "monitor-acoes/1.0 (automated daily digest)"}
    noticias = []

    for sub in subreddits:
        url = (
            "https://www.reddit.com/r/{}/search.json"
            "?q={}&sort=new&limit=15&restrict_sr=on".format(sub, query)
        )
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 429:
                logger.warning("Reddit rate-limit em r/%s, pulando", sub)
                time.sleep(2)
                continue
            if resp.status_code != 200:
                logger.debug("Reddit r/%s: HTTP %d", sub, resp.status_code)
                time.sleep(0.5)
                continue

            posts = resp.json().get("data", {}).get("children", [])
            count = 0
            for post in posts:
                d = post.get("data", {})
                ups = d.get("ups", 0)
                if ups < 10:
                    continue
                titulo = d.get("title", "").strip()
                if not titulo:
                    continue
                created = d.get("created_utc")
                ts = datetime.fromtimestamp(created, tz=timezone.utc) if created else None
                noticias.append({
                    "titulo":       titulo,
                    "fonte":        "reddit/r/{}".format(sub),
                    "link":         "https://reddit.com{}".format(d.get("permalink", "")),
                    "publicado_ts": ts,
                    "origem":       "reddit",
                    "score_av":     0.0,
                    "ups":          ups,
                })
                count += 1
                if count >= max_por_sub:
                    break

            time.sleep(0.6)

        except Exception as exc:
            logger.error("Reddit r/%s (%s): %s", sub, ticker, exc)

    return noticias


def buscar_noticias_ticker(ticker, eh_americano=True, av_cache=None, top_n=5):
    """Agrega, deduplica, pontua e devolve top_n noticias ranqueadas."""
    todas = []

    todas += _google_news(ticker)
    time.sleep(0.4)

    if av_cache and ticker in av_cache:
        todas += av_cache[ticker]

    todas += _reddit(ticker, eh_americano=eh_americano)

    if not todas:
        return []

    todas = _deduplicar(todas)

    for n in todas:
        n["score_final"] = _score_noticia(n, ticker)

    todas.sort(key=lambda x: x["score_final"], reverse=True)
    top = todas[:top_n]

    origens = [ORIGEM_LABEL.get(n["origem"], n["origem"]) for n in top]
    logger.info("%s: %d noticias selecionadas %s", ticker, len(top), origens)
    return top


def buscar_todas_noticias(amer_tickers, bras_tickers):
    """Ponto de entrada - retorna {ticker: [noticias]} para todo o portfolio."""
    logger.info("Alpha Vantage: batch para %d tickers americanos...", len(amer_tickers))
    av_cache = _alpha_vantage_batch(amer_tickers)

    resultado = {}

    for ticker in amer_tickers:
        resultado[ticker] = buscar_noticias_ticker(
            ticker, eh_americano=True, av_cache=av_cache
        )
        time.sleep(0.5)

    for ticker in bras_tickers:
        resultado[ticker] = buscar_noticias_ticker(
            ticker, eh_americano=False, av_cache=None
        )
        time.sleep(0.5)

    return resultado