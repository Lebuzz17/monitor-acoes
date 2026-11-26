import pytest

from fundo.valuation import builder, dcf, exemplo, recalc


def _p(**kw):
    base = dict(receita_base=100.0, crescimento=(0.0, 0.0), margem_ebitda=(0.5, 0.5), da_pct=(0.0, 0.0),
                capex_pct=(0.0, 0.0), nwc_pct=0.0, aliquota_ir=0.0, rf=0.10, erp=0.05, beta=0.0,
                kd_pre=0.10, peso_divida=0.0, g_terminal=0.0, divida_liquida=100.0, acoes=10.0,
                preco_atual=30.0)
    base.update(kw)
    return dcf.Premissas(**base)


def test_dcf_a_mao():
    # FCFF = 50 por ano; WACC = Ke = 10%; g = 0 => EV = 50/0.10 = 500; equity = 400; 40 por acao
    r = dcf.valuation(_p())
    assert r["wacc"] == pytest.approx(0.10)
    assert r["soma_vp"] == pytest.approx(50 / 1.1 + 50 / 1.21)
    assert r["ev"] == pytest.approx(500.0)
    assert r["valor_por_acao"] == pytest.approx(40.0)
    assert r["upside"] == pytest.approx(40 / 30 - 1)


def test_wacc_com_divida_e_imposto():
    p = _p(beta=1.0, aliquota_ir=0.34, peso_divida=0.4)  # Ke = 15%, Kd liq = 6.6%
    ke, kd, w = dcf.wacc(p)
    assert (ke, kd) == (pytest.approx(0.15), pytest.approx(0.066))
    assert w == pytest.approx(0.6 * 0.15 + 0.4 * 0.066)


def test_fcff_completo_a_mao():
    # ano 1: receita 110; EBITDA 55; D&A 11; EBIT 44; IR 25% = 11; NOPAT 33; capex 16.5;
    # dNWC = 0.1*(110-100) = 1; FCFF = 33 + 11 - 16.5 - 1 = 26.5
    p = _p(crescimento=(0.10, 0.0), da_pct=(0.10, 0.10), capex_pct=(0.15, 0.15), nwc_pct=0.10,
           aliquota_ir=0.25)
    assert dcf.projetar(p)["fcff"][0] == pytest.approx(26.5)


def test_wacc_menor_que_g_e_recusado():
    with pytest.raises(ValueError):
        dcf.valuation(_p(g_terminal=0.10))


def test_vetores_de_tamanhos_diferentes_sao_recusados():
    with pytest.raises(ValueError):
        _p(margem_ebitda=(0.5,))


def test_mais_crescimento_e_mais_valor_e_mais_wacc_e_menos_valor():
    base = dcf.valuation(_p(crescimento=(0.05, 0.05)))["valor_por_acao"]
    assert dcf.valuation(_p(crescimento=(0.10, 0.10)))["valor_por_acao"] > base
    assert dcf.valuation(_p(crescimento=(0.05, 0.05), rf=0.12))["valor_por_acao"] < base


def test_sensibilidade_centro_igual_ao_valuation():
    p = _p(g_terminal=0.03)
    s = dcf.sensibilidade(p)
    assert s[(0.0, 0.03)] == pytest.approx(dcf.valuation(p)["valor_por_acao"])
    assert s[(-0.02, 0.03)] > s[(0.0, 0.03)] > s[(0.02, 0.03)]


def test_alvo_ponderado_exige_probabilidades_validas():
    res = {"bear": {"valor_por_acao": 10}, "base": {"valor_por_acao": 20}, "bull": {"valor_por_acao": 30}}
    assert dcf.alvo_ponderado(res, {"bear": 0.25, "base": 0.5, "bull": 0.25}) == pytest.approx(20.0)
    with pytest.raises(ValueError):
        dcf.alvo_ponderado(res, {"bear": 0.5, "base": 0.5, "bull": 0.5})


def test_ipca_anual_de_cenario():
    pi4q = list(range(1, 21))
    assert dcf.ipca_anual_de_cenario(pi4q, 2) == [0.04, 0.08]
    with pytest.raises(ValueError):
        dcf.ipca_anual_de_cenario(pi4q, 6)


def test_builder_recusa_premissa_sem_fonte(tmp_path):
    prem, probs, fontes = exemplo.premissas_exemplo()
    del fontes["beta"]
    with pytest.raises(builder.PremissaSemFonte, match="beta"):
        builder.construir(tmp_path / "x.xlsx", "Exemplo", "EXEM3", prem, probs, fontes)
    prem, probs, fontes = exemplo.premissas_exemplo()
    fontes["rf"]["trecho"] = ""
    with pytest.raises(builder.PremissaSemFonte, match="rf"):
        builder.construir(tmp_path / "x.xlsx", "Exemplo", "EXEM3", prem, probs, fontes)


def test_builder_gera_formulas_e_azul(tmp_path):
    from openpyxl import load_workbook
    prem, probs, fontes = exemplo.premissas_exemplo()
    out = tmp_path / "m.xlsx"
    meta = builder.construir(out, "Exemplo Transmissao", "EXEM3", prem, probs, fontes)
    wb = load_workbook(out)
    assert wb.sheetnames == ["Capa", "Premissas", "Proj_Bear", "Proj_Base", "Proj_Bull", "Valuation",
                             "Sensibilidade", "Log"]
    assert str(wb["Proj_Base"]["C6"].value).startswith("=")           # receita e formula
    assert wb["Valuation"]["C16"].value == "=C14/C15"
    assert wb["Premissas"]["D10"].font.color.rgb.endswith("0000FF")  # premissa digitada em azul
    assert meta["celulas"]["alvo_ponderado"] == "Valuation!B22"


@pytest.mark.skipif(recalc.achar_soffice() is None, reason="LibreOffice nao instalado")
def test_excel_recalculado_bate_com_python(tmp_path):
    prem, probs, fontes = exemplo.premissas_exemplo()
    out = tmp_path / "m.xlsx"
    meta = builder.construir(out, "Exemplo Transmissao", "EXEM3", prem, probs, fontes)
    recalc.recalcular(out)
    r = recalc.conferir(out, meta["celulas"], prem, probs)
    assert r["ok"]


@pytest.mark.skipif(recalc.achar_soffice() is None, reason="LibreOffice nao instalado")
def test_conferencia_pega_erro_de_formula(tmp_path):
    from openpyxl import load_workbook
    prem, probs, fontes = exemplo.premissas_exemplo()
    out = tmp_path / "m.xlsx"
    meta = builder.construir(out, "Exemplo Transmissao", "EXEM3", prem, probs, fontes)
    wb = load_workbook(out)
    wb["Proj_Base"]["C8"] = "=C6*C7*1.01"  # erro plantado: EBITDA 1% maior
    wb.save(out)
    recalc.recalcular(out)
    with pytest.raises(recalc.ErroDeConferencia):
        recalc.conferir(out, meta["celulas"], prem, probs)
