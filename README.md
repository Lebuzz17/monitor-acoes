# Monitor de Ações

Monitoramento diário de portfólio com análise de sentimento via Groq (LLaMA 3.3 70B) e envio de resumo pelo Telegram.

## Estrutura

```
monitor-acoes/
├── src/
│   ├── cotacoes.py      # cotações via yfinance
│   ├── noticias.py      # notícias via Google News RSS
│   ├── analise.py       # análise de sentimento via Groq
│   ├── notificacao.py   # envio via Telegram
│   └── main.py          # orquestrador
├── logs/                # logs automáticos
├── data/                # dados auxiliares
├── .env                 # credenciais (não commitar)
├── .env.example         # template
└── requirements.txt
```

## Configuração

### 1. Instalar dependências

```bash
cd ~/monitor-acoes
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Criar o Bot no Telegram

1. Abra o Telegram e procure por **@BotFather**
2. Envie `/newbot` e siga as instruções
3. Copie o **token** fornecido (ex: `123456789:AAF...`)

### 3. Obter seu TELEGRAM_CHAT_ID

1. Procure por **@userinfobot** no Telegram
2. Envie qualquer mensagem → ele retorna seu `Id`
3. Ou: envie uma mensagem para seu bot, depois acesse:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   e pegue o valor de `message.chat.id`

### 4. Configurar credenciais

```bash
nano ~/monitor-acoes/.env
```

Preencha:
```
GROQ_API_KEY=sua_chave_aqui
TELEGRAM_BOT_TOKEN=seu_token_aqui
TELEGRAM_CHAT_ID=seu_chat_id_aqui
```

### 5. Testar manualmente

```bash
cd ~/monitor-acoes
source .venv/bin/activate
python src/main.py
```

## Cron Job (18h horário de Brasília)

Já configurado automaticamente. Para verificar:

```bash
crontab -l
```

Para editar:

```bash
crontab -e
```

Linha configurada (18h BRT = 21h UTC, seg-sex):
```
0 21 * * 1-5 /home/ubuntu/monitor-acoes/.venv/bin/python /home/ubuntu/monitor-acoes/src/main.py >> /home/ubuntu/monitor-acoes/logs/cron.log 2>&1
```

## Logs

```bash
tail -f ~/monitor-acoes/logs/monitor.log
tail -f ~/monitor-acoes/logs/cron.log
```
