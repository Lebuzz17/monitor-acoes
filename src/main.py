#!/usr/bin/env python3
"""Monitor de Acoes - executa diariamente e envia resumo via Telegram."""

import sys
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(ROOT / "logs" / "monitor.log"),
    ],
)
logger = logging.getLogger("main")


def main():
    from src.cotacoes import buscar_todas_cotacoes, get_todos_tickers
    from src.noticias import buscar_todas_noticias, buscar_noticias_macro
    from src.analise import gerar_alertas, gerar_contexto_macro
    from src.notificacao import montar_mensagem, enviar_telegram, buscar_macro
    try:
        from src.extrator import reset_stats, get_stats, get_firecrawl_usage
        _extrator_ok = True
    except ImportError:
        _extrator_ok = False

    if _extrator_ok:
        reset_stats()

    logger.info("=== Iniciando Monitor de Acoes ===")

    logger.info("Buscando cotacoes...")
    cotacoes = buscar_todas_cotacoes()

    amer, bras = get_todos_tickers()
    logger.info("Buscando noticias de portfolio (%d tickers)...", len(amer) + len(bras))
    noticias = buscar_todas_noticias(amer, bras)

    logger.info("Buscando noticias macro dedicadas...")
    noticias_macro = buscar_noticias_macro()

    logger.info("Gerando alertas com Groq...")
    alertas = gerar_alertas(cotacoes, noticias)

    logger.info("Gerando contexto macro com Groq...")
    contexto_macro = gerar_contexto_macro(noticias_macro)

    logger.info("Buscando dados macro numericos...")
    macro = buscar_macro()

    logger.info("Montando mensagem Telegram...")
    mensagem = montar_mensagem(cotacoes, alertas, macro, contexto_macro)

    logger.info("Enviando via Telegram...")
    enviar_telegram(mensagem)

    if _extrator_ok:
        stats = get_stats()
        fc_usado, fc_limite = get_firecrawl_usage()
        logger.info("=== Stats de extracao de conteudo ===")
        logger.info("  NewsAPI:       %d artigos", stats.get("newsapi", 0))
        logger.info("  BeautifulSoup: %d artigos", stats.get("beautifulsoup", 0))
        logger.info("  Firecrawl:     %d artigos", stats.get("firecrawl", 0))
        logger.info("  Fallback:      %d artigos", stats.get("fallback", 0))
        logger.info("  Firecrawl uso mensal: %d / %d", fc_usado, fc_limite)
        print("\n========== STATS DE EXTRACAO ==========")
        print("  NewsAPI:       {} artigos".format(stats.get("newsapi", 0)))
        print("  BeautifulSoup: {} artigos".format(stats.get("beautifulsoup", 0)))
        print("  Firecrawl:     {} artigos".format(stats.get("firecrawl", 0)))
        print("  Fallback:      {} artigos".format(stats.get("fallback", 0)))
        print("  Firecrawl uso mensal: {} / {}".format(fc_usado, fc_limite))
        print("========================================\n")

    logger.info("=== Concluido com sucesso! ===")


if __name__ == "__main__":
    main()