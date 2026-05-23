import time
import logging
import yfinance as yf

logger = logging.getLogger(__name__)

PORTFOLIO = {
    "americano": {
        "acoes": ["AAPL", "UNH", "AMZN", "GOOGL", "V", "MA", "MSFT", "JPM", "BAC"],
        "etfs":  ["IVV", "QQQ", "GBTC"],
        "ucits": ["EIMI.L"],
    },
    "brasileiro": ["BBAS3.SA", "BOVA11.SA", "ITUB4.SA", "VALE3.SA", "SMALL11.SA", "PRIO3.SA"],
}


def get_todos_tickers():
    amer = (
        PORTFOLIO["americano"]["acoes"]
        + PORTFOLIO["americano"]["etfs"]
        + PORTFOLIO["americano"]["ucits"]
    )
    return amer, PORTFOLIO["brasileiro"]


def buscar_cotacao(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d")
        if hist.empty or len(hist) < 1:
            logger.warning("Sem dados para %s", ticker)
            return {"ticker": ticker, "preco": None, "variacao": None, "moeda": "?"}

        preco_atual = float(hist["Close"].iloc[-1])
        variacao = 0.0
        if len(hist) >= 2:
            prev = float(hist["Close"].iloc[-2])
            if prev > 0:
                variacao = ((preco_atual - prev) / prev) * 100

        moeda = "USD"
        try:
            moeda = t.info.get("currency", "USD") or "USD"
        except Exception:
            pass

        return {
            "ticker": ticker,
            "preco": round(preco_atual, 2),
            "variacao": round(variacao, 2),
            "moeda": moeda,
        }
    except Exception as exc:
        logger.error("Erro ao buscar %s: %s", ticker, exc)
        return {"ticker": ticker, "preco": None, "variacao": None, "moeda": "?"}


def buscar_todas_cotacoes() -> dict:
    resultado = {"americano": {}, "brasileiro": {}}
    amer, bras = get_todos_tickers()
    for ticker in amer:
        resultado["americano"][ticker] = buscar_cotacao(ticker)
        time.sleep(0.3)
    for ticker in bras:
        resultado["brasileiro"][ticker] = buscar_cotacao(ticker)
        time.sleep(0.3)
    return resultado
