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

    logger.info("=== Concluido com sucesso! ===")


if __name__ == "__main__":
    main()