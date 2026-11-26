import math

import numpy as np
import pytest

from fundo.risco import estresse as e
from fundo.risco import liquidez as l


def test_betas_ols_recupera_coeficientes():
    rng = np.random.default_rng(0)
    f1, f2 = rng.normal(0, 0.01, 500), rng.normal(0, 0.02, 500)
    y = 0.0002 + 1.3 * f1 - 0.5 * f2 + rng.normal(0, 0.0005, 500)
    b = e.betas_ols(y, {"ibov": f1, "btc": f2})
    assert b["ibov"] == pytest.approx(1.3, abs=0.05)
    assert b["btc"] == pytest.approx(-0.5, abs=0.05)


def test_estresse_hipotetico_a_mao():
    pesos = {"A": 0.6, "BTC": 0.1}
    sens = {"A": {"USDBRL": 0.3}, "BTC": {"BTC": 1.0}}
    # BRL +20%: A sobe 0.3*20 = 6% -> contribui 0.6*6 = 3.6 ; BTC nao reage
    r = e.estresse_hipotetico(pesos, sens, {"USDBRL": 20.0})
    assert r["pnl_pct"] == pytest.approx(3.6)
    # BTC -50%: 0.1 * -50 = -5
    assert e.estresse_hipotetico(pesos, sens, {"BTC": -50.0})["pnl_pct"] == pytest.approx(-5.0)


def test_pior_janela_encontra_a_queda():
    p = np.array([100, 101, 102, 90, 80, 85, 86, 87.0])
    i, j, r = e.pior_janela(p, 2)  # pior em 2 pregoes: 102 -> 80 (indices 2 -> 4)
    assert (i, j) == (2, 4)
    assert r == pytest.approx((80 / 102 - 1) * 100)


def test_estresse_historico_reaplica_janela():
    precos = {"A": np.array([100.0, 90.0, 80.0]), "B": np.array([50.0, 50.0, 55.0])}
    r = e.estresse_historico({"A": 0.5, "B": 0.5, "C": 0.1}, precos, (0, 2))
    assert r["pnl_pct"] == pytest.approx(0.5 * -20 + 0.5 * 10)
    assert r["sem_historico"] == ["C"]


def test_dias_para_zerar():
    assert l.dias_para_zerar(1000, 10_000, 0.2) == pytest.approx(0.5)
    assert l.dias_para_zerar(100_000, 10_000, 0.2) == pytest.approx(50.0)
    assert l.dias_para_zerar(0, 0) == 0.0
    assert math.isinf(l.dias_para_zerar(1, 0))
    with pytest.raises(ValueError):
        l.dias_para_zerar(1, 1, 0)


def test_relatorio_liquidez_aponta_violacoes():
    r = l.relatorio_liquidez({"A": 1000, "B": 100_000, "C": 5}, {"A": 10_000, "B": 10_000}, limite_dias=5)
    assert r["violam_limite"] == ["B", "C"]  # C sem volume = infinito
    assert r["dias"]["A"] == pytest.approx(0.5)
