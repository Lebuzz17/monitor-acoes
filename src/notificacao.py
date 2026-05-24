"""
notificacao.py - formata e envia a mensagem diaria via Telegram.

Formato 3 blocos:
  Bloco 1 - SEMAFORO: semaforo por cor (verde/cinza/vermelho) por variacao
  Bloco 2 - ALERTAS:  textos curtos gerados pelo Groq para movimentos relevantes
  Bloco 3 - MACRO:    S&P, Ibovespa, DXY, Treasury 10y, USD/BRL
"""

import os
import html
import asyncio
import logging
from datetime import datetime

import pytz
import yfinance as yf
from telegram import Bot
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)
TZ_BR = pytz.timezone("America/Sao_Paulo")

ETFS_US = {"IVV", "QQQ", "GBTC", "EIMI.L"}

MACRO_TICKERS = {
    "S&P 500":       "^GSPC",
    "Ibovespa":      "^BVSP",
    "DXY":           "DX-Y.NYB",
    "Treasury 10y":  "^TNX",
    "USD/BRL":       "BRL=X",
}


# ─── Formatadores ────────────────────────────────────────────────────────────

def _fmt_preco(preco, moeda="USD"):
    if preco is None:
        return "N/D"
    if moeda == "BRL":
        return "R${:.2f}".format(preco)
    if moeda == "GBp":
        return "{:.2f}p".format(preco)
    return "${:.2f}".format(preco)


def _fmt_var_pct(variacao):
    if variacao is None:
        return "N/D"
    sinal = "+" if variacao > 0 else ""
    return "{}{:.2f}%".format(sinal, variacao)


def _fmt_br_large(valor):
    """Formata inteiro grande no padrao brasileiro: 137.245 ou 5.847."""
    if valor is None:
        return "N/D"
    s = "{:,.0f}".format(abs(valor))          # "137,245"
    return ("-" if valor < 0 else "") + s.replace(",", ".")   # "137.245"


def _fmt_br_small(valor, decimais=2):
    """Formata numero pequeno no padrao brasileiro: 104,23."""
    if valor is None:
        return "N/D"
    return "{:.{}f}".format(valor, decimais).replace(".", ",")


def _emoji_var(variacao):
    if variacao is None:
        return ""
    if variacao > 0:
        return "📈"
    if variacao < 0:
        return "📉"
    return "➡️"


# ─── Dados macro ─────────────────────────────────────────────────────────────

def buscar_macro():
    """Busca indicadores macro via yfinance. Retorna {nome: {preco, variacao}}."""
    macro = {}
    for nome, ticker in MACRO_TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if hist.empty:
                macro[nome] = {"preco": None, "variacao": None}
                continue
            preco = float(hist["Close"].iloc[-1])
            if len(hist) >= 2:
                prev = float(hist["Close"].iloc[-2])
                variacao = (preco - prev) / prev * 100 if prev else None
            else:
                variacao = None
            macro[nome] = {"preco": preco, "variacao": variacao}
        except Exception as exc:
            logger.error("Macro %s (%s): %s", nome, ticker, exc)
            macro[nome] = {"preco": None, "variacao": None}
    return macro


# ─── Semaforo ────────────────────────────────────────────────────────────────

def _cor_semaforo(variacao):
    if variacao is None:
        return "cinza"
    if variacao > 0.5:
        return "verde"
    if variacao < -0.5:
        return "vermelho"
    return "cinza"


def _fmt_ativo_semaforo(ticker, variacao):
    t_clean = ticker.replace(".SA", "").replace(".L", "")
    if variacao is None:
        return t_clean
    sinal = "+" if variacao > 0 else ""
    return "{} {}{:.1f}%".format(t_clean, sinal, variacao)


def _linha_semaforo(ativos_dict):
    """Agrupa ativos por cor, ordena por variacao desc, retorna linhas HTML."""
    verde     = []
    cinza     = []
    vermelho  = []
    for ticker, d in ativos_dict.items():
        var = d.get("variacao")
        texto = _fmt_ativo_semaforo(ticker, var)
        cor = _cor_semaforo(var)
        if cor == "verde":
            verde.append((var or 0, texto))
        elif cor == "vermelho":
            vermelho.append((var or 0, texto))
        else:
            cinza.append((var or 0, texto))

    verde.sort(key=lambda x: x[0], reverse=True)
    cinza.sort(key=lambda x: x[0], reverse=True)
    vermelho.sort(key=lambda x: x[0], reverse=True)

    linhas = []
    if verde:
        linhas.append("🟢 " + "  ".join(t for _, t in verde))
    if cinza:
        linhas.append("⚪ " + "  ".join(t for _, t in cinza))
    if vermelho:
        linhas.append("🔴 " + "  ".join(t for _, t in vermelho))
    return linhas


def _linha_etfs(ativos_dict):
    """Uma linha compacta para ETFs com emoji individual."""
    items = sorted(ativos_dict.items(), key=lambda x: x[1].get("variacao") or 0, reverse=True)
    partes = []
    for ticker, d in items:
        var = d.get("variacao")
        emoji = "🟢" if _cor_semaforo(var) == "verde" else ("🔴" if _cor_semaforo(var) == "vermelho" else "⚪")
        partes.append("{} {}".format(emoji, _fmt_ativo_semaforo(ticker, var)))
    return "ETFs: " + "  ".join(partes)


def _bloco_semaforo(cotacoes):
    linhas = ["<b>🚦 SEMÁFORO</b>", ""]

    amer = cotacoes.get("americano", {})
    acoes_us  = {t: d for t, d in amer.items() if t not in ETFS_US}
    etfs_us   = {t: d for t, d in amer.items() if t in ETFS_US}

    if acoes_us:
        linhas.append("<b>🇺🇸 Ações Americanas</b>")
        linhas.extend(_linha_semaforo(acoes_us))

    if etfs_us:
        linhas.append(_linha_etfs(etfs_us))

    linhas.append("")

    bras = cotacoes.get("brasileiro", {})
    if bras:
        linhas.append("<b>🇧🇷 Ações Brasileiras</b>")
        linhas.extend(_linha_semaforo(bras))

    return linhas


# ─── Alertas ─────────────────────────────────────────────────────────────────

def _bloco_alertas(cotacoes, alertas):
    linhas = ["<b>🔔 ALERTAS</b>", ""]

    todos = []
    for mercado, lista in alertas.items():
        for a in lista:
            todos.append((mercado, a))

    if not todos:
        linhas.append("<i>Nenhum alerta significativo no momento.</i>")
        return linhas

    for mercado, alerta in todos:
        ticker  = alerta.get("ticker", "")
        texto   = alerta.get("texto", "")
        dados   = cotacoes.get(mercado, {}).get(ticker, {})
        var     = dados.get("variacao")
        preco   = dados.get("preco")
        moeda   = dados.get("moeda", "USD")

        preco_s = _fmt_preco(preco, moeda)
        var_s   = _fmt_var_pct(var)
        emoji   = _emoji_var(var)

        ticker_clean = ticker.replace(".SA", "").replace(".L", "")
        linhas.append(
            "<b>{}</b> {} <code>{}</code> {}".format(
                ticker_clean, preco_s, var_s, emoji
            )
        )
        linhas.append(html.escape(texto))
        linhas.append("")

    return linhas


# ─── Macro ───────────────────────────────────────────────────────────────────

def _bloco_macro(macro):
    linhas = ["<b>🌍 MACRO</b>", ""]

    def _linha(nome, m):
        preco = m.get("preco")
        var   = m.get("variacao")
        emoji = _emoji_var(var)
        var_s = "({}{})".format(_fmt_var_pct(var), " " + emoji if emoji else "") if var is not None else ""

        if nome == "S&P 500":
            p_s = _fmt_br_large(preco)
        elif nome == "Ibovespa":
            p_s = _fmt_br_large(preco)
        elif nome == "Treasury 10y":
            p_s = "{}%".format(_fmt_br_small(preco, 2)) if preco is not None else "N/D"
        elif nome == "USD/BRL":
            p_s = "R$ {}".format(_fmt_br_small(preco, 2)) if preco is not None else "N/D"
        else:
            p_s = _fmt_br_small(preco, 1) if preco is not None else "N/D"

        return "<code>{:<14}</code> {}  {}".format(nome, p_s, var_s)

    for nome, m in macro.items():
        linhas.append(_linha(nome, m))

    return linhas


# ─── Mensagem principal ───────────────────────────────────────────────────────

def montar_mensagem(cotacoes, alertas, macro):
    agora = datetime.now(TZ_BR)
    cabecalho = [
        "<b>📊 MONITOR DE AÇÕES — {}</b>".format(agora.strftime("%d/%m/%Y %H:%M")),
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    sep = ["", "━━━━━━━━━━━━━━━━━━━━━━", ""]

    rodape = [
        "",
        "<i>🤖 Groq LLaMA 3.3 70B</i>",
    ]

    partes = (
        cabecalho
        + _bloco_semaforo(cotacoes)
        + sep
        + _bloco_alertas(cotacoes, alertas)
        + sep
        + _bloco_macro(macro)
        + rodape
    )

    return "\n".join(partes)


# ─── Envio Telegram ──────────────────────────────────────────────────────────

async def _enviar_async(mensagem):
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
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


def enviar_telegram(mensagem):
    asyncio.run(_enviar_async(mensagem))