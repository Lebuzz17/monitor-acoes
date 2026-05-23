#!/usr/bin/env python3
"""Monitor de Acoes — executa diariamente e envia resumo via Telegram."""

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
    from src.noticias import buscar_todas_noticias
    from src.analise import analisar_portfolio, gerar_resumo_geral
    from src.notificacao import montar_mensagem, enviar_telegram

    logger.info("=== Iniciando Monitor de Acoes ===")

    logger.info("Buscando cotacoes...")
    cotacoes = buscar_todas_cotacoes()

    amer, bras = get_todos_tickers()
    todos = amer + bras

    logger.info("Buscando noticias (%d tickers)...", len(todos))
    noticias = buscar_todas_noticias(todos)

    logger.info("Analisando com Groq...")
    analises = analisar_portfolio(cotacoes, noticias)

    logger.info("Gerando resumo geral...")
    resumo = gerar_resumo_geral(cotacoes)

    logger.info("Montando mensagem Telegram...")
    mensagem = montar_mensagem(cotacoes, analises, resumo)

    logger.info("Enviando via Telegram...")
    enviar_telegram(mensagem)

    logger.info("=== Concluido com sucesso! ===")


if __name__ == "__main__":
    main()
