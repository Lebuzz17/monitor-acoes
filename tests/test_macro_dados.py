from datetime import date, timedelta

import numpy as np
import pytest

from fundo.macro import cenarios, dados, filtros, taylor_eua
from fundo.macro import semiestrutural_br as sm


class Resp:
    def __init__(self, dado, texto=""):
        self._d, self.text, self.status_code = dado, texto, 200

    def json(self):
        return self._d


@pytest.fixture(autouse=True)
def cache_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(dados, "CACHE_DIR", tmp_path / "cache")


def test_sgs_parseia_ordena_e_descarta_datas_futuras(monkeypatch):
    amanha = (date.today() + timedelta(days=1)).strftime("%d/%m/%Y")
    bruto = [{"data": "02/01/2020", "valor": "2.5"}, {"data": "01/01/2020", "valor": "2.0"},
             {"data": amanha, "valor": "99"}]
    monkeypatch.setattr(dados, "_http", lambda url, params=None, tentativas=3: Resp(bruto))
    s = dados.sgs(432, inicio=date(2020, 1, 1))
    assert s == [(date(2020, 1, 1), 2.0), (date(2020, 1, 2), 2.5)]


def test_cache_nao_colide_com_prefixo_longo_igual():
    a = "x" * 200 + "A"
    b = "x" * 200 + "B"
    dados._cache_put(a, [1]); dados._cache_put(b, [2])
    assert dados._cache_get(a, 60) == [1] and dados._cache_get(b, 60) == [2]


def test_http_nao_repete_erro_4xx(monkeypatch):
    chamadas = []

    class R:
        status_code = 400

    monkeypatch.setattr(dados.requests, "get", lambda *a, **k: chamadas.append(1) or R())
    monkeypatch.setattr(dados.time, "sleep", lambda s: None)
    with pytest.raises(dados.DadosIndisponiveis):
        dados._http("http://x")
    assert len(chamadas) == 1


def test_sgs_limite_de_ultimos():
    with pytest.raises(ValueError):
        dados.sgs(432, ultimos=50)


def test_fred_parseia_csv_e_ignora_ausentes(monkeypatch):
    csv = "observation_date,DFF\n2026-01-01,3.5\n2026-01-02,.\n2026-01-03,3.6\n"
    monkeypatch.setattr(dados, "_http", lambda url, params=None, tentativas=3: Resp(None, csv))
    assert dados.fred("DFF") == [(date(2026, 1, 1), 3.5), (date(2026, 1, 3), 3.6)]


def test_variacao_12m():
    s = [(date(2025, i % 12 + 1, 1), 100.0) for i in range(12)] + [(date(2026, 1, 1), 103.0)]
    assert dados.variacao_12m(s) == pytest.approx(3.0)


def test_hp_filter_propriedades():
    t = np.arange(120.0)
    y = 0.5 * t  # reta: sem ciclo
    tend, ciclo = filtros.hp_filter(y, 1600)
    assert np.allclose(ciclo, 0, atol=1e-6)
    rng = np.random.default_rng(1)
    y2 = y + np.sin(t / 3) + rng.normal(0, 0.05, t.size)
    tend2, ciclo2 = filtros.hp_filter(y2, 1600)
    assert abs(ciclo2.mean()) < 0.1 and np.allclose(tend2 + ciclo2, y2)


def test_hiato_hp_percentual_serie_constante():
    assert np.allclose(filtros.hiato_hp_percentual(np.full(40, 100.0)), 0, atol=1e-9)


def test_regra_taylor_a_mao():
    # r*=0.75, pi=3, hiato=1: base = 0.75 + 3 + 0.5*(3-2) = 4.25; taylor93 = 4.75; balanceada = 5.25
    t, b = taylor_eua.regra_taylor(3.0, 1.0, 0.75)
    assert t == pytest.approx(4.75) and b == pytest.approx(5.25)


def test_cenarios_probabilidades_devem_somar_um():
    cal, est = cenarios.estado_de_dados(13.75, 13.75, 4.6, 0.7, 5.1, -1.0, 2.0, 3.9)
    ruins = [cenarios.Cenario("base", 0.5)]
    with pytest.raises(ValueError):
        cenarios.projetar(cal, est, ruins)


def test_ancora_reproduz_o_consenso():
    cal, est = cenarios.estado_de_dados(13.75, 13.75, 4.6, 0.7, 5.1, -1.0, 2.0, 3.9)
    c = cenarios.ancorar_no_focus(cal, est, 5.0)
    p = cenarios.projetar(cal, est, ancora=c)
    assert p["cenarios"]["base"]["h4"]["ipca_4q"] == pytest.approx(5.0, abs=1e-3)
    # ordem dos cenarios: bear tem mais inflacao e mais cambio que bull
    assert p["cenarios"]["bear"]["h4"]["ipca_4q"] > p["cenarios"]["bull"]["h4"]["ipca_4q"]
    assert p["cenarios"]["bear"]["h4"]["cambio_nominal_pct"] > p["cenarios"]["bull"]["h4"]["cambio_nominal_pct"]


def test_hiato_trimestral_descarta_trimestre_incompleto_e_serie_constante_da_zero():
    serie = [(date(2010 + m // 12, m % 12 + 1, 1), 100.0) for m in range(14 * 12 + 2)]  # 2 meses sobrando
    assert cenarios.hiato_trimestral(serie) == pytest.approx(0.0, abs=1e-9)
    with pytest.raises(dados.DadosIndisponiveis):
        cenarios.hiato_trimestral(serie[:20])
