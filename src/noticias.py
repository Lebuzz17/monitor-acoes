import time
import logging
import urllib.parse
import feedparser

logger = logging.getLogger(__name__)


def _limpar_ticker(ticker: str) -> str:
    return ticker.replace(".SA", "").replace(".L", "")


def buscar_noticias_ticker(ticker: str, max_noticias: int = 5) -> list:
    nome = _limpar_ticker(ticker)
    query = urllib.parse.quote(f"{nome} stock")
    url = (
        f"https://news.google.com/rss/search?q={query}"
        f"&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    )
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
        noticias = []
        for entry in feed.entries[:max_noticias]:
            titulo = entry.get("title", "").strip()
            if titulo:
                noticias.append({
                    "titulo": titulo,
                    "link": entry.get("link", ""),
                    "publicado": entry.get("published", ""),
                })
        return noticias
    except Exception as exc:
        logger.error("Erro noticias %s: %s", ticker, exc)
        return []


def buscar_todas_noticias(tickers: list) -> dict:
    resultado = {}
    for ticker in tickers:
        logger.info("Noticias: %s", ticker)
        resultado[ticker] = buscar_noticias_ticker(ticker)
        time.sleep(0.8)
    return resultado
