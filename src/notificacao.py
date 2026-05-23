import os
import html
import asyncio
import logging
from datetime import datetime
import pytz
from telegram import Bot
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)
TZ_BR = pytz.timezone("America/Sao_Paulo")


def _fmt_preco(preco, moeda: str) -> str:
    if preco is None:
        return "N/D"
    if moeda == "BRL":
        return f"R${preco:.2f}"
    if moeda == "GBp":
        return f"{preco:.2f}p"
    return f"${preco:.2f}"


def _fmt_variacao(variacao) -> str:
    if variacao is None:
        return "N/D"
    if variacao > 0:
        return f"📈 +{variacao:.2f}%"
    if variacao < 0:
        return f"📉 {variacao:.2f}%"
    return f"➡️ 0.00%"


def montar_mensagem(cotacoes: dict, analises: dict, resumo_geral: str) -> str:
    agora = datetime.now(TZ_BR)
    linhas = [
        f"📊 <b>MONITOR DE AÇÕES — {agora.strftime('%d/%m/%Y %H:%M')}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    secoes = [
        ("americano", "🇺🇸 <b>PORTFÓLIO AMERICANO</b>"),
        ("brasileiro", "🇧🇷 <b>PORTFÓLIO BRASILEIRO</b>"),
    ]

    for chave, titulo in secoes:
        linhas.append(titulo)
        linhas.append("")
        for ticker, dados in cotacoes.get(chave, {}).items():
            analise = analises.get(chave, {}).get(ticker, {})
            sent = analise.get("sentimento", "⚠️")
            p = _fmt_preco(dados.get("preco"), dados.get("moeda", "USD"))
            v = _fmt_variacao(dados.get("variacao"))
            linhas.append(f"{sent} <b>{ticker}</b> — {p} | {v}")

            for i, n in enumerate(analise.get("top_noticias", [])[:3], 1):
                t = html.escape(str(n)[:95] + ("…" if len(str(n)) > 95 else ""))
                linhas.append(f"   {i}. {t}")

            resumo_t = analise.get("resumo", "")
            if resumo_t:
                linhas.append(f"   <i>💬 {html.escape(str(resumo_t))}</i>")

            linhas.append("")

        linhas.append("━━━━━━━━━━━━━━━━━━━━━━")
        linhas.append("")

    linhas.append("📝 <b>RESUMO DO DIA</b>")
    linhas.append(html.escape(resumo_geral))
    linhas.append("")
    linhas.append("<i>🤖 Powered by Groq LLaMA 3.3 70B</i>")
    return "\n".join(linhas)


async def _enviar_async(mensagem: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nao configurados no .env")

    bot = Bot(token=token)
    max_len = 4096

    if len(mensagem) <= max_len:
        await bot.send_message(chat_id=chat_id, text=mensagem, parse_mode=ParseMode.HTML)
        return

    partes, atual = [], ""
    for linha in mensagem.split("\n"):
        if len(atual) + len(linha) + 1 > max_len:
            if atual:
                partes.append(atual.strip())
            atual = linha + "\n"
        else:
            atual += linha + "\n"
    if atual.strip():
        partes.append(atual.strip())

    for parte in partes:
        await bot.send_message(chat_id=chat_id, text=parte, parse_mode=ParseMode.HTML)
        await asyncio.sleep(0.5)


def enviar_telegram(mensagem: str):
    asyncio.run(_enviar_async(mensagem))
