"""Configuracao central do fundo. Valores sensiveis vem do .env, nunca daqui."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("FUNDO_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.getenv("FUNDO_DB", DATA_DIR / "fundo.db"))
TIMEZONE = "America/Sao_Paulo"

# Modo de operacao. "paper" = simulado; "testnet" = Binance Spot Testnet.
# Dinheiro real NAO existe nesta versao: so entra numa fase futura, atras de
# uma chave que so o dono liga (FUNDO_DINHEIRO_REAL, ainda sem uso no codigo).
MODO = os.getenv("FUNDO_MODO", "paper")
assert MODO in ("paper", "testnet"), "modo invalido: dinheiro real nao e suportado"

# --- Groq (nomes ficam aqui porque o Groq troca/aposenta modelos) -----------
MODELOS = {
    "triagem": os.getenv("FUNDO_MODELO_TRIAGEM", "openai/gpt-oss-20b"),
    "grande": os.getenv("FUNDO_MODELO_GRANDE", "openai/gpt-oss-120b"),
}
# Rodizio entre modelos grandes: cada modelo tem cota diaria propria no Groq.
# Preencher na Fase 0 com o que a conta realmente lista (client.models.list()).
MODELOS_GRANDES_RODIZIO = [
    m for m in os.getenv("FUNDO_MODELOS_RODIZIO", "openai/gpt-oss-120b,qwen/qwen3.8-27b").split(",") if m
]

# Limites do plano gratis (CONFIRMAR no console do Groq; fontes divergem).
LIMITES = {
    # modelo: (tokens por minuto, requisicoes por dia, tokens por dia)
    # Confirmado no console do Groq em 2026-11-26 (30 req/min em todos).
    # Os llama antigos (3.1-8b, 3.3-70b) nao existem mais para esta conta.
    "openai/gpt-oss-120b": (8000, 1000, 200_000),
    "openai/gpt-oss-20b": (8000, 1000, 200_000),
    "qwen/qwen3.8-27b": (8000, 1000, 200_000),
}
LIMITE_PADRAO = (6000, 1000, 100_000)  # modelo desconhecido: conservador
MARGEM_SEGURANCA = 0.9  # usa no maximo 90% de cada limite

# Cotas internas (tokens/dia, somadas sobre todos os modelos)
COTA_CHAT_DIA = int(os.getenv("FUNDO_COTA_CHAT", 20_000))      # chat com o CIO
RESERVA_CRISE_DIA = int(os.getenv("FUNDO_RESERVA_CRISE", 15_000))  # so o modo crise usa
MAX_TOKENS_ENTRADA = 4000  # cada chamada cabe em ~4 mil tokens de entrada
