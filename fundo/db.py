"""SQLite do fundo: esquema, conexao e helpers.

Um unico arquivo (data/fundo.db), modo WAL. As tabelas cobrem o que o plano
exige: posicoes, ordens, faixas de preco, propostas/aprovacoes, memos dos
analistas, premissas com fonte, valuations, fontes baixadas (URL/data/hash),
cenarios macro, metricas de risco, eventos de crise, diario de decisoes, chat
e consumo do LLM.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fundo import config

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

-- regulagens mutaveis (nivel de aprovacao, N empresas/semana, modo...)
CREATE TABLE IF NOT EXISTS config (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL,
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ativos (
    ticker TEXT PRIMARY KEY,
    nome TEXT,
    classe TEXT NOT NULL,            -- acao_br, acao_us, etf, cripto, caixa
    setor TEXT,
    moeda TEXT NOT NULL DEFAULT 'BRL',
    playbook TEXT,                   -- commodities, juros_longos, consumo_saude, tecnologia...
    ativo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS posicoes (
    ticker TEXT PRIMARY KEY REFERENCES ativos(ticker),
    quantidade REAL NOT NULL,
    preco_medio REAL NOT NULL,
    livro TEXT NOT NULL DEFAULT 'longo',   -- longo | tatico
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ordens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criada_em TEXT NOT NULL DEFAULT (datetime('now')),
    ticker TEXT NOT NULL,
    lado TEXT NOT NULL CHECK (lado IN ('compra', 'venda')),
    quantidade REAL NOT NULL,
    preco REAL,
    corretora TEXT NOT NULL,         -- paper | binance_testnet | mt5
    livro TEXT NOT NULL DEFAULT 'longo',
    origem TEXT NOT NULL,            -- faixa | parcela | crise | manual
    status TEXT NOT NULL DEFAULT 'pendente',
    custo REAL NOT NULL DEFAULT 0,
    detalhe TEXT
);

-- faixas de preco definidas pelo comite (ordens condicionais pre-aprovadas)
CREATE TABLE IF NOT EXISTS faixas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('compra', 'reforco', 'reducao', 'saida')),
    preco_gatilho REAL NOT NULL,
    peso_alvo REAL,
    parcelas INTEGER NOT NULL DEFAULT 1,
    valida_ate TEXT,
    ativa INTEGER NOT NULL DEFAULT 1,
    valuation_id INTEGER
);

-- portao de aprovacao do dono (empresa + preco-alvo, mudancas > 10% etc.)
CREATE TABLE IF NOT EXISTS propostas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criada_em TEXT NOT NULL DEFAULT (datetime('now')),
    tipo TEXT NOT NULL,              -- empresa_alvo | mudanca_alvo | politica | ...
    ticker TEXT,
    resumo TEXT NOT NULL,
    payload TEXT,                    -- JSON
    status TEXT NOT NULL DEFAULT 'pendente'
        CHECK (status IN ('pendente', 'aprovada', 'reprovada', 'expirada')),
    prazo TEXT,
    decidida_em TEXT,
    motivo TEXT
);

CREATE TABLE IF NOT EXISTS memos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    agente TEXT NOT NULL,
    ticker TEXT,
    tipo TEXT NOT NULL,              -- tese | parecer | objecao | previa | revisao | semanal
    texto TEXT NOT NULL
);

-- premissa sem fonte e recusada (fonte_id e trecho obrigatorios)
CREATE TABLE IF NOT EXISTS fontes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    baixada_em TEXT NOT NULL DEFAULT (datetime('now')),
    sha256 TEXT NOT NULL,
    caminho_local TEXT,
    origem TEXT                      -- ri | cvm | sec | bc | outro
);

CREATE TABLE IF NOT EXISTS valuations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    versao INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'rascunho'
        CHECK (status IN ('rascunho', 'aprovado', 'arquivado')),
    alvo_bear REAL, alvo_base REAL, alvo_bull REAL,
    preco_ref REAL,
    confianca INTEGER,               -- 1 a 5
    arquivo TEXT,                    -- caminho do xlsx
    git_commit TEXT,
    correcoes_dono INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (ticker, versao)
);

CREATE TABLE IF NOT EXISTS premissas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    valuation_id INTEGER NOT NULL REFERENCES valuations(id),
    nome TEXT NOT NULL,
    valor REAL NOT NULL,
    unidade TEXT,
    fonte_id INTEGER NOT NULL REFERENCES fontes(id),
    trecho TEXT NOT NULL,
    proposta_por TEXT,
    criada_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cenarios_macro (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL,
    cenario TEXT NOT NULL CHECK (cenario IN ('bear', 'base', 'bull')),
    probabilidade REAL NOT NULL,
    variaveis TEXT NOT NULL          -- JSON: selic, ipca, cambio, pib, fed, ust10, brent, minerio
);

CREATE TABLE IF NOT EXISTS risco_diario (
    data TEXT NOT NULL,
    livro TEXT NOT NULL DEFAULT 'total',
    es_975 REAL, var_95 REAL, var_99 REAL,
    vol_ewma REAL, drawdown REAL, pnl REAL,
    excecao_var INTEGER NOT NULL DEFAULT 0,
    detalhe TEXT,                    -- JSON (contribuicoes, exposicoes, estresse...)
    PRIMARY KEY (data, livro)
);

CREATE TABLE IF NOT EXISTS eventos_crise (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio TEXT NOT NULL,
    fim TEXT,
    gatilho TEXT NOT NULL,
    detalhe TEXT,
    revisao_cio TEXT
);

-- diario de decisoes: resultado esperado + probabilidade, para calibrar (Brier)
CREATE TABLE IF NOT EXISTS diario (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    agente TEXT NOT NULL,
    decisao TEXT NOT NULL,
    esperado TEXT,
    probabilidade REAL,
    horizonte TEXT,
    resultado TEXT,
    acertou INTEGER
);

CREATE TABLE IF NOT EXISTS chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    papel TEXT NOT NULL CHECK (papel IN ('dono', 'cio')),
    texto TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    dia TEXT NOT NULL,               -- AAAA-MM-DD no fuso do fundo
    modelo TEXT NOT NULL,
    tarefa TEXT NOT NULL,
    prioridade TEXT NOT NULL,        -- normal | chat | crise
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 1,
    erro TEXT
);
CREATE INDEX IF NOT EXISTS ix_llm_usage_dia ON llm_usage (dia, modelo);
CREATE INDEX IF NOT EXISTS ix_ordens_ticker ON ordens (ticker, criada_em);
CREATE INDEX IF NOT EXISTS ix_faixas_ticker ON faixas (ticker, ativa);
"""

CONFIG_PADRAO = {
    "nivel_aprovacao": "0",      # 0 a 3 (ver plano)
    "empresas_por_semana": "1",  # N de 1 a 3
    "nivel_curriculo": "1",
}


def conectar(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path or config.DB_PATH)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")
    return con


def inicializar(path: Path | str | None = None) -> sqlite3.Connection:
    """Cria o esquema (idempotente) e grava a regulagem padrao."""
    con = conectar(path)
    con.executescript(SCHEMA)
    con.execute(
        "INSERT OR IGNORE INTO meta (chave, valor) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    for k, v in CONFIG_PADRAO.items():
        con.execute("INSERT OR IGNORE INTO config (chave, valor) VALUES (?, ?)", (k, v))
    con.commit()
    return con


@contextmanager
def transacao(con: sqlite3.Connection):
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


def get_config(con: sqlite3.Connection, chave: str, padrao: str | None = None) -> str | None:
    row = con.execute("SELECT valor FROM config WHERE chave = ?", (chave,)).fetchone()
    return row["valor"] if row else padrao


def set_config(con: sqlite3.Connection, chave: str, valor: str) -> None:
    con.execute(
        "INSERT INTO config (chave, valor) VALUES (?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = datetime('now')",
        (chave, str(valor)),
    )
    con.commit()
