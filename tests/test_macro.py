import numpy as np
import pytest

from fundo.macro import semiestrutural_br as m


def test_equilibrio_e_ponto_fixo():
    cal = m.Calibracao()
    r = m.simular(cal, m.equilibrio(cal))
    assert np.allclose(r["pi4q"], cal.meta, atol=1e-6)
    assert np.allclose(r["selic"], cal.juro_neutro + cal.meta, atol=1e-6)
    assert np.allclose(r["hiato"], 0, atol=1e-6)
    assert np.allclose(r["cambio_acum"], 0, atol=1e-6)


# Respostas ao impulso publicadas pelo BC (RI jun/2024, boxe de atualizacao dos modelos),
# modelo agregado, IPCA acumulado em 4 trimestres (pp).
def _q4(choque):
    return m.resposta_ao_impulso(choque=choque)["pi4q"][3]


def test_irf_cambio_bate_com_o_bc():
    # BC: depreciacao permanente de 10% => +0,96 pp
    assert _q4("cambio") == pytest.approx(0.96, rel=0.20)


def test_irf_hiato_bate_com_o_bc():
    # BC: choque de +1% no hiato => +0,49 pp
    assert _q4("hiato") == pytest.approx(0.49, rel=0.20)


def test_irf_selic_bate_com_o_bc():
    # BC: +1 pp na Selic por 4 trimestres => -0,27 pp (aqui -0,32; tolerancia de 30%)
    assert _q4("selic") == pytest.approx(-0.27, rel=0.30)


def test_repasse_cambial_por_componente():
    r = m.resposta_ao_impulso(choque="cambio")
    # BC: livres +0,72 pp e administrados +1,65 pp (4 trimestres)
    assert r["pi_livres"][:4].sum() == pytest.approx(0.72, rel=0.30)
    assert r["pi_adm"][:4].sum() == pytest.approx(1.65, rel=0.15)


def test_selic_alta_aprecia_o_cambio_e_reduz_hiato():
    r = m.resposta_ao_impulso(choque="selic")
    assert r["cambio_acum"][0] < 0
    assert r["hiato"][3] < 0


def test_taylor_reage_a_expectativa_alta():
    cal = m.Calibracao()
    est = m.equilibrio(cal)
    est.exp12m = 6.0  # expectativas desancoradas
    r = m.simular(cal, est)
    assert r["selic"][0] > est.selic  # BC sobe juros


def test_vetor_exogeno_com_tamanho_errado():
    cal = m.Calibracao()
    with pytest.raises(ValueError):
        m.simular(cal, m.equilibrio(cal), m.Exogenas(choque_cambio=np.zeros(3)))


def test_nao_convergencia_e_erro_explicito():
    cal = m.Calibracao()
    with pytest.raises(RuntimeError, match="nao convergiu"):
        m.simular(cal, m.equilibrio(cal), m.Exogenas(choque_cambio=np.r_[10.0, np.zeros(19)]), iteracoes=1)


def test_cambio_nominal_inclui_tendencia_de_ppc():
    cal = m.Calibracao()
    r = m.simular(cal, m.equilibrio(cal))
    dppp = (cal.meta - cal.meta_externa) / 4
    assert r["cambio_nominal_acum"][3] == pytest.approx(4 * dppp)
    assert r["cambio_acum"][3] == pytest.approx(0.0, abs=1e-9)
