import sqlite3

import pytest

from fundo import db


@pytest.fixture
def con(tmp_path):
    return db.inicializar(tmp_path / "t.db")


def test_inicializar_e_idempotente(tmp_path):
    p = tmp_path / "t.db"
    db.inicializar(p).close()
    con = db.inicializar(p)  # segunda vez nao falha nem duplica
    assert db.get_config(con, "nivel_aprovacao") == "0"
    assert con.execute("SELECT valor FROM meta WHERE chave='schema_version'").fetchone()[0] == "1"


def test_wal_ativo(con):
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_set_config_atualiza(con):
    db.set_config(con, "nivel_aprovacao", "2")
    assert db.get_config(con, "nivel_aprovacao") == "2"


def test_valuation_status_invalido_e_recusado(con):
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO valuations (ticker, versao, status) VALUES ('X', 1, 'qualquer')")


def test_premissa_exige_fonte_e_trecho(con):
    con.execute("INSERT INTO valuations (ticker, versao) VALUES ('TAEE11', 1)")
    with pytest.raises(sqlite3.IntegrityError):  # sem fonte_id
        con.execute("INSERT INTO premissas (valuation_id, nome, valor, trecho) VALUES (1, 'g', 0.03, 't')")
    with pytest.raises(sqlite3.IntegrityError):  # fonte inexistente (FK)
        con.execute("INSERT INTO premissas (valuation_id, nome, valor, fonte_id, trecho) "
                    "VALUES (1, 'g', 0.03, 99, 't')")
    con.execute("INSERT INTO fontes (url, sha256) VALUES ('http://ri', 'abc')")
    con.execute("INSERT INTO premissas (valuation_id, nome, valor, fonte_id, trecho) "
                "VALUES (1, 'g', 0.03, 1, 'reajuste pelo IPCA')")


def test_ordem_lado_invalido(con):
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO ordens (ticker, lado, quantidade, corretora, origem) "
                    "VALUES ('X', 'xx', 1, 'paper', 'manual')")
