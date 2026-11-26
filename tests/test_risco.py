import math

import numpy as np
import pytest

from fundo.risco import metricas as m


# Retornos de teste: -10%, -9%, ..., -1% e +1..+80% (100 observacoes: 10 perdas conhecidas + ganhos)
R100 = np.array([-0.10, -0.09, -0.08, -0.07, -0.06, -0.05, -0.04, -0.03, -0.02, -0.01]
                + [0.01 * i for i in range(1, 91)])


def test_var_historico_a_mao():
    # 100 obs, 5% pior: quantil 5% interpolado entre -0.06 (5a) e -0.05 (6a) pior -> posicao 4.95
    # np.quantile linear: indice (n-1)*q = 99*0.05 = 4.95 -> -0.06 + 0.95*(0.01) = -0.0505
    assert m.var_historico(R100, 0.95) == pytest.approx(0.0505)


def test_es_historico_a_mao():
    # ES 95% em 100 obs = media dos 5 piores: (0.10+0.09+0.08+0.07+0.06)/5 = 0.08
    assert m.es_historico(R100, 0.95) == pytest.approx(0.08)
    # ES 97,5% = media dos ceil(2.5)=3 piores: (0.10+0.09+0.08)/3 = 0.09
    assert m.es_historico(R100, 0.975) == pytest.approx(0.09)


def test_es_maior_ou_igual_ao_var():
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.01, 1000)
    assert m.es_historico(r, 0.975) >= m.var_historico(r, 0.975)


def test_vol_ewma_constante():
    # retornos de mesmo modulo => variancia EWMA = modulo^2 => vol = modulo
    r = np.array([0.01, -0.01] * 50)
    assert m.vol_ewma(r) == pytest.approx(0.01)


def test_var_parametrico_normal():
    r = np.array([0.01, -0.01] * 50)
    assert m.var_parametrico_ewma(r, 0.95) == pytest.approx(1.6448536 * 0.01, rel=1e-5)
    # ES normal 97,5%: sigma * pdf(1.95996)/0.025 = sigma * 2.3378
    assert m.es_parametrico_ewma(r, 0.975) == pytest.approx(2.3378 * 0.01, rel=1e-3)


def test_kupiec_valores_conhecidos():
    # 5 excecoes em 100 com VaR 95%: exatamente o esperado => LR = 0, p = 1
    lr, p = m.kupiec_pof(5, 100, 0.95)
    assert lr == pytest.approx(0.0, abs=1e-9)
    assert p == pytest.approx(1.0)
    # 10 excecoes em 100: LR = 2*[10 ln(0.10/0.05) + 90 ln(0.90/0.95)] = 4.13;
    # qui-quadrado(1 g.l.) em 4.13 => p = 0.042 (valor de tabela)
    lr, p = m.kupiec_pof(10, 100, 0.95)
    esperado = 2 * (10 * math.log(0.10 / 0.05) + 90 * math.log(0.90 / 0.95))
    assert lr == pytest.approx(esperado)
    assert lr == pytest.approx(4.13, abs=0.01)
    assert p == pytest.approx(0.042, abs=0.001)
    # 15 excecoes: rejeita claramente
    assert m.kupiec_pof(15, 100, 0.95)[1] < 0.001
    # zero excecoes em 250 dias (VaR 99%): definido, sem erro de log(0)
    lr, p = m.kupiec_pof(0, 250, 0.99)
    assert lr > 0 and 0 < p < 1


def test_backtest_var_conta_excecoes():
    rng = np.random.default_rng(7)
    r = rng.normal(0, 0.01, 1250)
    bt = m.backtest_var(r, 0.95, janela=250)
    assert bt["n"] == 1000
    assert 25 < bt["excecoes"] < 80  # ~50 esperado
    assert bt["rejeitado_5pct"] is False


def test_contribuicao_vol_soma_vol_total():
    cov = np.array([[0.04, 0.01, 0.0], [0.01, 0.09, 0.02], [0.0, 0.02, 0.16]])
    w = np.array([0.5, 0.3, 0.2])
    c = m.contribuicao_vol(w, cov)
    assert c.sum() == pytest.approx(math.sqrt(w @ cov @ w))


def test_contribuicao_es_soma_es_total():
    rng = np.random.default_rng(3)
    R = rng.normal(0, 0.01, (500, 4))
    w = np.array([0.4, 0.3, 0.2, 0.1])
    c = m.contribuicao_es(R, w, 0.975)
    assert c.sum() == pytest.approx(m.es_historico(R @ w, 0.975))


def test_drawdown():
    # +10%, -20%, +5%: pico 1.10; fundo 0.88 => dd = -20%; depois 0.924 => -16%
    dd = m.drawdown([0.10, -0.20, 0.05])
    assert dd[0] == pytest.approx(0.0)
    assert dd[1] == pytest.approx(-0.20)
    assert dd[2] == pytest.approx(0.924 / 1.10 - 1)
    assert m.max_drawdown([0.10, -0.20, 0.05]) == pytest.approx(-0.20)


def test_semaforo():
    assert m.semaforo(0.010, 0.018, 0.025) == "OK"
    assert m.semaforo(0.020, 0.018, 0.025) == "ATENCAO"
    assert m.semaforo(0.025, 0.018, 0.025) == "ROMPIDO"


def test_entradas_invalidas():
    with pytest.raises(ValueError):
        m.var_historico([])
    with pytest.raises(ValueError):
        m.es_historico([0.01, float("nan")])
    with pytest.raises(ValueError):
        m.kupiec_pof(5, 0)
