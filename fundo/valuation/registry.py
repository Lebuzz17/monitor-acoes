"""Registro de valuations no banco: fontes, premissas com fonte obrigatoria, status e aprovacao.

Regras (da politica):
  * premissa sem fonte (documento baixado e guardado) e sem trecho citado e RECUSADA;
  * valuation so e `aprovado` pelo dono (empresa + preco-alvo); sem resposta, nada acontece;
  * mudanca de alvo acima de 10% sempre exige o dono, em qualquer nivel de aprovacao;
  * so valuation `aprovado` alimenta faixas de preco e ordens.
"""

import hashlib
import sqlite3
from pathlib import Path

import requests

from fundo import config, db

LIMITE_MUDANCA_ALVO = 0.10


class PremissaRecusada(Exception):
    pass


class AprovacaoNecessaria(Exception):
    pass


# ---------------------------------------------------------------- fontes
def registrar_fonte(con: sqlite3.Connection, url: str, conteudo: bytes, origem: str,
                    pasta: Path | None = None) -> int:
    """Guarda uma copia local do documento (hash SHA-256) e registra em `fontes`."""
    if origem not in ("ri", "cvm", "sec", "bc", "outro"):
        raise ValueError("origem invalida")
    sha = hashlib.sha256(conteudo).hexdigest()
    existente = con.execute("SELECT id FROM fontes WHERE sha256 = ? AND url = ?", (sha, url)).fetchone()
    if existente:
        return existente["id"]
    pasta = Path(pasta or config.DATA_DIR / "fontes")
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{sha[:16]}"
    caminho.write_bytes(conteudo)
    cur = con.execute("INSERT INTO fontes (url, sha256, caminho_local, origem) VALUES (?, ?, ?, ?)",
                      (url, sha, str(caminho), origem))
    con.commit()
    return cur.lastrowid


def baixar_fonte(con: sqlite3.Connection, url: str, origem: str, pasta: Path | None = None) -> int:
    r = requests.get(url, timeout=60, headers={"User-Agent": "fundo-pessoal/1.0"})
    r.raise_for_status()
    return registrar_fonte(con, url, r.content, origem, pasta)


def trecho_existe_na_fonte(con: sqlite3.Connection, fonte_id: int, trecho: str) -> bool:
    """Confere que o trecho citado aparece no documento guardado (texto). Para PDFs/binarios a
    verificacao e feita sobre o texto extraido antes de registrar (ver `registrar_fonte_texto`)."""
    row = con.execute("SELECT caminho_local FROM fontes WHERE id = ?", (fonte_id,)).fetchone()
    if not row or not row["caminho_local"]:
        return False
    try:
        texto = Path(row["caminho_local"]).read_bytes().decode("utf-8", errors="ignore")
    except OSError:
        return False
    norm = lambda s: " ".join(s.lower().split())
    return norm(trecho) in norm(texto)


# ------------------------------------------------------------ valuations
def criar_valuation(con, ticker: str, alvo_bear: float, alvo_base: float, alvo_bull: float,
                    preco_ref: float, confianca: int, arquivo: str | None = None,
                    git_commit: str | None = None) -> int:
    if not (1 <= confianca <= 5):
        raise ValueError("confianca deve ser de 1 a 5")
    versao = (con.execute("SELECT COALESCE(MAX(versao), 0) FROM valuations WHERE ticker = ?",
                          (ticker,)).fetchone()[0]) + 1
    cur = con.execute(
        "INSERT INTO valuations (ticker, versao, status, alvo_bear, alvo_base, alvo_bull, preco_ref, "
        "confianca, arquivo, git_commit) VALUES (?, ?, 'rascunho', ?, ?, ?, ?, ?, ?, ?)",
        (ticker, versao, alvo_bear, alvo_base, alvo_bull, preco_ref, confianca, arquivo, git_commit))
    con.commit()
    return cur.lastrowid


def adicionar_premissa(con, valuation_id: int, nome: str, valor: float, unidade: str,
                       fonte_id: int | None, trecho: str, proposta_por: str,
                       exigir_trecho_no_documento: bool = True) -> int:
    if not fonte_id:
        raise PremissaRecusada(f"premissa '{nome}' sem fonte")
    if not (trecho and trecho.strip()):
        raise PremissaRecusada(f"premissa '{nome}' sem trecho citado")
    if not con.execute("SELECT 1 FROM fontes WHERE id = ?", (fonte_id,)).fetchone():
        raise PremissaRecusada(f"premissa '{nome}': fonte {fonte_id} nao existe")
    if exigir_trecho_no_documento and not trecho_existe_na_fonte(con, fonte_id, trecho):
        raise PremissaRecusada(f"premissa '{nome}': o trecho citado nao consta no documento guardado")
    cur = con.execute(
        "INSERT INTO premissas (valuation_id, nome, valor, unidade, fonte_id, trecho, proposta_por) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", (valuation_id, nome, valor, unidade, fonte_id, trecho, proposta_por))
    con.commit()
    return cur.lastrowid


def alvo_vigente(con, ticker: str):
    """Valuation `aprovado` mais recente do ticker (ou None). Unico que pode gerar faixas/ordens."""
    return con.execute("SELECT * FROM valuations WHERE ticker = ? AND status = 'aprovado' "
                       "ORDER BY versao DESC LIMIT 1", (ticker,)).fetchone()


def exige_dono(con, valuation_id: int) -> tuple[bool, str]:
    """Esta mudanca passa pelo dono neste nivel de aprovacao? (nivel 0 e 1: sempre; 2: so excecoes;
    3: so as que nunca desligam). Retorna (exige, motivo)."""
    v = con.execute("SELECT * FROM valuations WHERE id = ?", (valuation_id,)).fetchone()
    nivel = int(db.get_config(con, "nivel_aprovacao", "0"))
    anterior = alvo_vigente(con, v["ticker"])
    if anterior is not None and anterior["alvo_base"]:
        mud = abs(v["alvo_base"] / anterior["alvo_base"] - 1.0)
        if mud > LIMITE_MUDANCA_ALVO:
            return True, f"alvo muda {mud:.0%} (> {LIMITE_MUDANCA_ALVO:.0%}): sempre exige o dono"
    if anterior is None and int(db.get_config(con, "nivel_curriculo", "1")) < _nivel_empresa(con, v["ticker"]):
        return True, "empresa acima do nivel de dificuldade ja aprovado: sempre exige o dono"
    if nivel <= 1:
        return True, f"nivel de aprovacao {nivel}: dono aprova empresa e alvo"
    if nivel == 2:
        return False, "nivel 2: aprovado com aviso (dono pode vetar em 7 dias)"
    return False, "nivel 3: automatico com aviso"


def _nivel_empresa(con, ticker: str) -> int:
    row = con.execute("SELECT valor FROM config WHERE chave = ?", (f"nivel_dificuldade:{ticker}",)).fetchone()
    return int(row["valor"]) if row else 1


def aprovar(con, valuation_id: int, por: str = "dono", motivo: str | None = None) -> None:
    """Marca `aprovado` e arquiva a versao aprovada anterior do mesmo ticker."""
    v = con.execute("SELECT * FROM valuations WHERE id = ?", (valuation_id,)).fetchone()
    if v is None or v["status"] != "rascunho":
        raise ValueError("so valuation em rascunho pode ser aprovado")
    exige, motivo_regra = exige_dono(con, valuation_id)
    if exige and por != "dono":
        raise AprovacaoNecessaria(motivo_regra)
    if not con.execute("SELECT 1 FROM premissas WHERE valuation_id = ?", (valuation_id,)).fetchone():
        raise PremissaRecusada("valuation sem nenhuma premissa registrada com fonte")
    con.execute("UPDATE valuations SET status = 'arquivado' WHERE ticker = ? AND status = 'aprovado'",
                (v["ticker"],))
    con.execute("UPDATE valuations SET status = 'aprovado' WHERE id = ?", (valuation_id,))
    con.commit()


def reprovar(con, valuation_id: int, motivo: str) -> None:
    con.execute("UPDATE valuations SET status = 'arquivado', correcoes_dono = correcoes_dono + 1 WHERE id = ?",
                (valuation_id,))
    con.execute("INSERT INTO memos (agente, ticker, tipo, texto) "
                "SELECT 'dono', ticker, 'parecer', ? FROM valuations WHERE id = ?", (motivo, valuation_id))
    con.commit()
