import pytest

from fundo import db
from fundo.valuation import placar, registry as reg


@pytest.fixture
def con(tmp_path):
    return db.inicializar(tmp_path / "t.db")


def _val(con, ticker="EXEM3", base=40.0):
    return reg.criar_valuation(con, ticker, base * 0.7, base, base * 1.3, 30.0, 3)


def _fonte(con, tmp_path, texto="O reajuste anual da RAP e feito pelo IPCA. A receita cresce 4,5% ao ano."):
    return reg.registrar_fonte(con, "https://ri.exemplo/release", texto.encode(), "ri", tmp_path / "f")


# ---------------- fontes e premissas ----------------
def test_fonte_guarda_copia_e_hash_e_nao_duplica(con, tmp_path):
    a = _fonte(con, tmp_path)
    b = _fonte(con, tmp_path)
    assert a == b
    row = con.execute("SELECT * FROM fontes WHERE id = ?", (a,)).fetchone()
    assert len(row["sha256"]) == 64 and row["origem"] == "ri"


def test_premissa_sem_fonte_ou_trecho_e_recusada(con, tmp_path):
    v = _val(con); f = _fonte(con, tmp_path)
    with pytest.raises(reg.PremissaRecusada):
        reg.adicionar_premissa(con, v, "g", 0.045, "%", None, "x", "analista")
    with pytest.raises(reg.PremissaRecusada):
        reg.adicionar_premissa(con, v, "g", 0.045, "%", f, "   ", "analista")
    with pytest.raises(reg.PremissaRecusada):
        reg.adicionar_premissa(con, v, "g", 0.045, "%", 999, "x", "analista")


def test_trecho_precisa_constar_no_documento(con, tmp_path):
    v = _val(con); f = _fonte(con, tmp_path)
    reg.adicionar_premissa(con, v, "g", 0.045, "%", f, "A receita cresce 4,5% ao ano", "analista")
    with pytest.raises(reg.PremissaRecusada, match="nao consta"):
        reg.adicionar_premissa(con, v, "g2", 0.09, "%", f, "A receita cresce 9% ao ano", "analista")


# ---------------- aprovacao ----------------
def _com_premissa(con, tmp_path, v):
    f = _fonte(con, tmp_path)
    reg.adicionar_premissa(con, v, "g", 0.045, "%", f, "A receita cresce 4,5% ao ano", "analista")


def test_so_o_dono_aprova_no_nivel_0(con, tmp_path):
    v = _val(con); _com_premissa(con, tmp_path, v)
    with pytest.raises(reg.AprovacaoNecessaria):
        reg.aprovar(con, v, por="sistema")
    reg.aprovar(con, v, por="dono")
    assert reg.alvo_vigente(con, "EXEM3")["id"] == v


def test_nao_aprova_sem_premissa_com_fonte(con):
    v = _val(con)
    with pytest.raises(reg.PremissaRecusada):
        reg.aprovar(con, v, por="dono")


def test_sem_aprovacao_nao_ha_alvo_vigente(con, tmp_path):
    v = _val(con); _com_premissa(con, tmp_path, v)
    assert reg.alvo_vigente(con, "EXEM3") is None  # rascunho nao vale


def test_nova_versao_aprovada_arquiva_a_anterior(con, tmp_path):
    v1 = _val(con, base=40.0); _com_premissa(con, tmp_path, v1); reg.aprovar(con, v1)
    v2 = _val(con, base=41.0); _com_premissa(con, tmp_path, v2); reg.aprovar(con, v2)
    status = {r["id"]: r["status"] for r in con.execute("SELECT id, status FROM valuations")}
    assert status[v1] == "arquivado" and status[v2] == "aprovado"


def test_mudanca_de_alvo_acima_de_10pct_exige_dono_mesmo_no_nivel_3(con, tmp_path):
    db.set_config(con, "nivel_aprovacao", "3")
    v1 = _val(con, base=40.0); _com_premissa(con, tmp_path, v1); reg.aprovar(con, v1)
    v2 = _val(con, base=50.0); _com_premissa(con, tmp_path, v2)  # +25%
    exige, motivo = reg.exige_dono(con, v2)
    assert exige and "sempre exige o dono" in motivo
    with pytest.raises(reg.AprovacaoNecessaria):
        reg.aprovar(con, v2, por="sistema")
    v3 = _val(con, base=41.0); _com_premissa(con, tmp_path, v3)  # +2,5% vs v1
    assert reg.exige_dono(con, v3)[0] is False
    reg.aprovar(con, v3, por="sistema")


def test_niveis_de_aprovacao(con, tmp_path):
    v = _val(con); _com_premissa(con, tmp_path, v)
    for nivel, esperado in (("0", True), ("1", True), ("2", False), ("3", False)):
        db.set_config(con, "nivel_aprovacao", nivel)
        assert reg.exige_dono(con, v)[0] is esperado


def test_empresa_acima_do_nivel_exige_dono_no_nivel_3(con, tmp_path):
    db.set_config(con, "nivel_aprovacao", "3")
    db.set_config(con, "nivel_curriculo", "1")
    db.set_config(con, "nivel_dificuldade:VALE3", "3")
    v = _val(con, "VALE3"); _com_premissa(con, tmp_path, v)
    exige, motivo = reg.exige_dono(con, v)
    assert exige and "nivel de dificuldade" in motivo


def test_reprovar_arquiva_conta_correcao_e_registra_motivo(con, tmp_path):
    v = _val(con); _com_premissa(con, tmp_path, v)
    reg.reprovar(con, v, "WACC alto demais")
    row = con.execute("SELECT status, correcoes_dono FROM valuations WHERE id = ?", (v,)).fetchone()
    assert (row["status"], row["correcoes_dono"]) == ("arquivado", 1)
    assert con.execute("SELECT texto FROM memos").fetchone()["texto"] == "WACC alto demais"


# ---------------- placar ----------------
def C(ticker, alvo, preco=30.0, conf=4, **kw):
    return placar.Candidata(ticker, alvo, alvo * 0.8, alvo * 1.2, preco, conf, **kw)


def test_elege_maior_retorno_ajustado_por_confianca():
    # A: +30% mas confianca 2 (0.65) = 0.195 ; B: +20% confianca 5 (1.0) = 0.20  -> B vence
    r = placar.eleger([C("A", 39.0, conf=2), C("B", 36.0, conf=5)], nivel_curriculo=1)
    assert r["eleitas"][0].ticker == "B"


def test_curriculo_exclui_empresa_acima_do_nivel():
    r = placar.eleger([C("A", 60.0, nivel_dificuldade=3), C("B", 36.0, nivel_dificuldade=1)], nivel_curriculo=1)
    assert [p.ticker for p in r["ranking"]] == ["B"]
    assert "nivel de dificuldade" in r["excluidas"][0].motivos_exclusao[0]


def test_retorno_acima_do_teto_gera_alerta_mas_nao_exclui():
    r = placar.pontuar(C("A", 60.0), nivel_curriculo=1)  # +100%
    assert r.elegivel and any("teto" in a for a in r.alertas)


def test_penalidades_de_liquidez_setor_e_recencia():
    base = placar.pontuar(C("A", 36.0), 1).score
    assert not placar.pontuar(C("A", 36.0, dias_para_zerar=8), 1).elegivel
    assert not placar.pontuar(C("A", 36.0, uso_limite_setor=1.0), 1).elegivel
    assert placar.pontuar(C("A", 36.0, uso_limite_setor=0.9), 1).score < base
    assert placar.pontuar(C("A", 36.0, dias_desde_aprovacao=10), 1).score == pytest.approx(base * 0.5)


def test_alvos_fora_de_ordem_geram_alerta():
    c = placar.Candidata("A", 30.0, 40.0, 20.0, 25.0, 3)
    assert any("fora de ordem" in a for a in placar.pontuar(c, 1).alertas)


def test_retorno_esperado_a_mao():
    assert placar.retorno_esperado(36.0, 30.0) == pytest.approx(0.20)
    with pytest.raises(ValueError):
        placar.retorno_esperado(0, 30)
