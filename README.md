# 📊 Monitor de Ações

Bot que roda uma vez por dia, analisa o seu portfólio de ações (Brasil + EUA) e manda um resumo direto no Telegram — cotações, alertas gerados por IA sobre os principais movimentos e contexto macroeconômico, tudo com base em notícias reais dos últimos dois dias, não só no preço.

Não é um script que lê preço e manda número. Ele busca notícias em várias fontes, extrai o conteúdo completo dos artigos mais relevantes (não só o título), e usa o Groq (LLaMA 3.3 70B) pra escrever uma análise curta explicando **por que** um ativo se moveu, com base no que foi realmente publicado — não em achismo do modelo.

## O que a mensagem diária traz

```
📊 MONITOR DE AÇÕES — 26/08/2026 11:50
━━━━━━━━━━━━━━━━━━━━━━

🚦 SEMÁFORO
🇺🇸 Ações Americanas
🟢 AAPL +1.2%  MSFT +0.8%
⚪ AMZN +0.1%
🔴 JPM -0.6%
ETFs: 🟢 IVV +0.9%  ⚪ QQQ +0.3%

🇧🇷 Ações Brasileiras
🟢 VALE3 +2.1%
⚪ ITUB4 s/d          ← sem dado disponível no dia

━━━━━━━━━━━━━━━━━━━━━━

🔔 ALERTAS
AAPL $227.30 +1.2% 📈
Ação sobe após [resumo do que a notícia real disse]...

━━━━━━━━━━━━━━━━━━━━━━

🌍 MACRO
S&P 500        6.481   (+0.4% 📈)
Ibovespa       137.245 (-0.2% 📉)
DXY            104,2
USD/BRL        R$ 5,42

Mercados seguem otimistas com dados de inflação nos EUA...

🤖 Groq LLaMA 3.3 70B
```

- **🚦 Semáforo** — visão rápida de todo o portfólio por cor (🟢 alta > 0.5%, 🔴 queda > 0.5%, ⚪ estável). Ativo sem cotação disponível no dia aparece como `s/d` em vez de sumir da lista.
- **🔔 Alertas** — só ativos com movimento relevante (≥ 1.5% ou notícia negativa de peso) ganham um parágrafo explicando o motivo, escrito pelo Groq com base nas notícias reais coletadas — nunca inventado.
- **🌍 Macro** — S&P 500, Ibovespa, DXY, Treasury 10y e USD/BRL, mais um parágrafo de contexto sobre o cenário do dia (Fed, geopolítica, commodities), gerado a partir de fontes macro dedicadas.

## Como funciona por baixo dos panos

```
┌─────────────┐   ┌──────────────────┐   ┌─────────────────┐   ┌──────────────┐
│  cotacoes.py │   │   noticias.py     │   │  extrator.py     │   │  analise.py  │
│  yfinance    │   │  agrega + filtra  │──▶│  busca conteúdo  │──▶│  Groq LLaMA  │
│  preço/var % │   │  notícias 48h     │   │  completo em     │   │  gera texto  │
└──────┬───────┘   └──────────────────┘   │  4 camadas       │   │  dos alertas │
       │                                   └──────────────────┘   └──────┬───────┘
       └──────────────────────┬───────────────────────────────────────────┘
                               ▼
                      ┌─────────────────┐
                      │ notificacao.py  │
                      │ monta mensagem  │
                      │ envia Telegram  │
                      └─────────────────┘
```

**1. Coleta de notícias** ([src/noticias.py](src/noticias.py)) — para cada ativo do portfólio, busca em Google News, Alpha Vantage, Reddit (r/investing, r/stocks, r/ValueInvesting, r/investimentos, r/financas), Seeking Alpha (ações americanas) e feeds RSS gerais (BrazilJournal, InfoMoney, MoneyTimes). Notícias com mais de 48h são descartadas antes de qualquer análise — se um ativo não tem nada recente, ele simplesmente não gera alerta naquele dia. Notícias macro vêm de um conjunto separado de fontes dedicadas (Fed, WSJ Markets, Investing.com, FT Markets, BrazilJournal, MoneyTimes).

**2. Extração de conteúdo completo** ([src/extrator.py](src/extrator.py)) — título de notícia sozinho não dá contexto suficiente para uma boa análise, então cada artigo relevante passa por até 4 camadas até conseguir o texto completo:

| Camada | Como funciona |
|---|---|
| 1. NewsAPI | busca o artigo pelo endpoint `/everything`, usa se vier com mais de 200 palavras |
| 2. BeautifulSoup | faz scraping direto da página e extrai o corpo do artigo (`<article>`, `<main>`, maior `<div>`) |
| 3. Firecrawl | para páginas pesadas em JS ou parcialmente bloqueadas; limitado a 450 chamadas/mês (dividido entre notícias do portfólio e macro por execução) para não estourar o plano grátis |
| 4. Fallback | se nada funcionar, usa só o título + resumo do RSS, marcado como `[resumo]` |

Todo conteúdo extraído passa por uma limpeza que remove menus, botões, links soltos e boilerplate de navegação antes de seguir para a análise.

**3. Análise via IA** ([src/analise.py](src/analise.py)) — o Groq recebe até 300 palavras por artigo (com corte automático se o total passar de ~4000 palavras) e escreve um alerta mais detalhado quando tem conteúdo completo disponível, ou mais curto quando só tem o título. Regra fixa no prompt: nada de inventar informação que não esteja nas notícias fornecidas.

**4. Envio** ([src/notificacao.py](src/notificacao.py)) — monta a mensagem nos 3 blocos acima e envia via Telegram Bot API, quebrando em múltiplas mensagens automaticamente se passar do limite de 4096 caracteres.

Tudo isso é orquestrado por [src/main.py](src/main.py), que roda uma vez por dia via cron e imprime estatísticas de quantos artigos vieram de cada camada de extração.

## Estrutura

```
monitor-acoes/
├── src/
│   ├── cotacoes.py       # preços e variação via yfinance — portfólio configurado aqui
│   ├── noticias.py       # agrega, deduplica e filtra notícias (48h) por ativo e macro
│   ├── extrator.py       # extração de conteúdo completo em 4 camadas + budget Firecrawl
│   ├── analise.py        # gera alertas e contexto macro via Groq
│   ├── notificacao.py    # monta a mensagem 3 blocos e envia pelo Telegram
│   └── main.py           # orquestrador — ponto de entrada do cron
├── config/
│   └── settings.py
├── logs/                 # logs de execução (gerado automaticamente)
├── .env                  # credenciais (não commitar — já está no .gitignore)
├── .env.example          # template das variáveis necessárias
└── requirements.txt
```

## Configuração

### 1. Clonar e criar o ambiente virtual

```bash
git clone https://github.com/Lebuzz17/monitor-acoes.git
cd monitor-acoes
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Criar o Bot no Telegram

1. Abra o Telegram e procure por **@BotFather**
2. Envie `/newbot` e siga as instruções
3. Copie o **token** fornecido (ex: `123456789:AAF...`)

### 3. Obter seu TELEGRAM_CHAT_ID

1. Procure por **@userinfobot** no Telegram
2. Envie qualquer mensagem → ele retorna seu `Id`
3. Ou: envie uma mensagem para seu bot, depois acesse
   `https://api.telegram.org/bot<TOKEN>/getUpdates` e pegue o valor de `message.chat.id`

### 4. Obter as chaves de API

| Variável | Onde obter | Necessária para |
|---|---|---|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) | análise de sentimento e alertas — **obrigatória** |
| `TELEGRAM_BOT_TOKEN` | @BotFather (passo 2) | envio da mensagem — **obrigatória** |
| `TELEGRAM_CHAT_ID` | @userinfobot (passo 3) | envio da mensagem — **obrigatória** |
| `ALPHA_VANTAGE_KEY` | [alphavantage.co](https://www.alphavantage.co/support/#api-key) | notícias com relevance_score (free: 25 req/dia) — opcional, degrada bem sem |
| `NEWS_API_KEY` | [newsapi.org](https://newsapi.org/register) | camada 1 de extração de conteúdo — opcional, o pipeline cai pra próxima camada sem ela |
| `FIRECRAWL_KEY` | [firecrawl.dev](https://www.firecrawl.dev/) | camada 3 de extração (páginas com JS/paywall) — opcional, plano free cobre o uso do bot |

### 5. Configurar credenciais

```bash
cp .env.example .env
nano .env   # ou qualquer editor
```

### 6. (Opcional) Ajustar o portfólio

Os tickers monitorados ficam no topo de [src/cotacoes.py](src/cotacoes.py):

```python
PORTFOLIO = {
    "americano": {
        "acoes": ["AAPL", "UNH", "AMZN", ...],
        "etfs":  ["IVV", "QQQ", "GBTC"],
        "ucits": ["EIMI.L"],
    },
    "brasileiro": ["BBAS3.SA", "BOVA11.SA", ...],
}
```

Tickers brasileiros usam o sufixo `.SA` (padrão Yahoo Finance).

### 7. Testar manualmente

```bash
source .venv/bin/activate
python src/main.py
```

Isso roda o pipeline completo, envia a mensagem para o seu Telegram e imprime no console quantos artigos vieram de cada camada de extração:

```
========== STATS DE EXTRACAO ==========
  NewsAPI:       0 artigos
  BeautifulSoup: 10 artigos
  Firecrawl:     17 artigos
  Fallback:      25 artigos
  Firecrawl uso mensal: 108 / 450
========================================
```

## Agendamento (cron)

O bot roda todo dia às 11:50 (horário de Brasília) — horário escolhido para já capturar a abertura do mercado americano no resumo.

```bash
crontab -e
```

```cron
50 14 * * * /caminho/para/monitor-acoes/.venv/bin/python /caminho/para/monitor-acoes/src/main.py >> /caminho/para/monitor-acoes/logs/cron.log 2>&1
```

(`14:50 UTC` = `11:50` horário de Brasília, sem horário de verão)

Para conferir se está ativo:

```bash
crontab -l
```

## Logs

```bash
tail -f logs/monitor.log   # log completo de cada execução
tail -f logs/cron.log      # saída específica do cron
```

O contador de uso do Firecrawl fica em `logs/firecrawl_usage.log` e reseta automaticamente no dia 1º de cada mês.
