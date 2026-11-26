import pytest

from fundo import config, db
from fundo.llm import LLM, Resposta, SemCota

M = "llama-3.3-70b-versatile"


class Falso:
    def __init__(self, tokens=(100, 50), falha=False):
        self.chamadas = 0
        self.tokens = tokens
        self.falha = falha

    def completar(self, modelo, mensagens, max_tokens, temperatura):
        self.chamadas += 1
        if self.falha:
            raise RuntimeError("429 rate limit")
        return Resposta("ok", modelo, *self.tokens)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELOS_GRANDES_RODIZIO", [M])
    monkeypatch.setattr(config, "LIMITES", {M: (6000, 1000, 10_000)})
    monkeypatch.setattr(config, "MARGEM_SEGURANCA", 1.0)
    monkeypatch.setattr(config, "RESERVA_CRISE_DIA", 2_000)
    monkeypatch.setattr(config, "COTA_CHAT_DIA", 3_000)
    con = db.inicializar(tmp_path / "t.db")
    cli = Falso()
    t = [1_000_000.0]
    llm = LLM(con, cli, relogio=lambda: t[0], dormir=lambda s: t.__setitem__(0, t[0] + s))
    return llm, cli, con, t


MSG = [{"role": "user", "content": "oi"}]


def test_registra_uso(ctx):
    llm, cli, con, _ = ctx
    r = llm.chamar("teste", MSG, max_tokens=100)
    assert r.texto == "ok"
    row = con.execute("SELECT tokens_in, tokens_out, tarefa, ok FROM llm_usage").fetchone()
    assert tuple(row) == (100, 50, "teste", 1)


def test_reserva_so_para_crise(ctx):
    llm, cli, con, _ = ctx
    # ja usou 7.900 tokens hoje; teto 10.000 - reserva 2.000 = 8.000 para o normal
    con.execute("INSERT INTO llm_usage (dia, modelo, tarefa, prioridade, tokens_in, tokens_out) "
                "VALUES (?, ?, 'x', 'normal', 7900, 0)", (llm._dia(), M))
    con.commit()
    with pytest.raises(SemCota):
        llm.chamar("normal", MSG, max_tokens=500)
    assert cli.chamadas == 0
    llm.chamar("crise", MSG, max_tokens=500, prioridade="crise")  # usa a reserva
    assert cli.chamadas == 1


def test_cota_do_chat_e_separada(ctx):
    llm, cli, con, _ = ctx
    con.execute("INSERT INTO llm_usage (dia, modelo, tarefa, prioridade, tokens_in, tokens_out) "
                "VALUES (?, ?, 'c', 'chat', 2800, 0)", (llm._dia(), M))
    con.commit()
    with pytest.raises(SemCota):
        llm.chamar("chat", MSG, max_tokens=500, prioridade="chat")
    llm.chamar("analise", MSG, max_tokens=500)  # normal nao e afetado pela cota do chat


def test_cota_zera_no_dia_seguinte(ctx):
    llm, cli, con, t = ctx
    con.execute("INSERT INTO llm_usage (dia, modelo, tarefa, prioridade, tokens_in, tokens_out) "
                "VALUES (?, ?, 'x', 'normal', 7900, 0)", (llm._dia(), M))
    con.commit()
    t[0] += 86_400
    llm.chamar("normal", MSG, max_tokens=500)


def test_entrada_grande_demais_e_recusada(ctx):
    llm, *_ = ctx
    with pytest.raises(ValueError):
        llm.chamar("x", [{"role": "user", "content": "a" * 20_000}])


def test_falha_do_provedor_e_registrada(ctx):
    llm, cli, con, _ = ctx
    cli.falha = True
    with pytest.raises(SemCota):
        llm.chamar("x", MSG, max_tokens=100)
    assert con.execute("SELECT ok, erro FROM llm_usage").fetchone()["ok"] == 0


def test_tpm_espera_a_janela(ctx, monkeypatch):
    llm, cli, con, t = ctx
    monkeypatch.setattr(config, "LIMITES", {M: (1000, 1000, 100_000)})
    cli.tokens = (400, 400)
    llm.chamar("a", MSG, max_tokens=700)
    inicio = t[0]
    llm.chamar("b", MSG, max_tokens=700)  # estouraria 1000 tpm: tem que esperar ~60 s
    assert t[0] - inicio >= 55


def test_prioridade_invalida(ctx):
    llm, *_ = ctx
    with pytest.raises(ValueError):
        llm.chamar("x", MSG, prioridade="vip")
