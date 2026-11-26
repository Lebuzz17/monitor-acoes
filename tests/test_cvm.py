import io
import zipfile

import pytest

from fundo.valuation import cvm

CAB = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;"
       "DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA\n")


def linha(ver, cd, ordem, conta, ds, valor, escala="MIL", nome="EMPRESA ÁGUA S.A."):
    return (f"11.111.111/0001-11;2025-12-31;{ver};{nome};{cd};DF;REAL;{escala};{ordem};"
            f"2025-01-01;2025-12-31;{conta};{ds};{valor};S\n")


@pytest.fixture
def zip_falso(tmp_path, monkeypatch):
    monkeypatch.setattr(cvm, "CACHE", tmp_path)
    dre = CAB + "".join([
        linha(1, "009999", "ÚLTIMO", "3.01", "Receita", "1000000.0"),       # versao antiga (descartada)
        linha(2, "009999", "ÚLTIMO", "3.01", "Receita", "2000000.0"),       # R$ 2.000 mi
        linha(2, "009999", "PENÚLTIMO", "3.01", "Receita", "1500000.0"),
        linha(2, "009999", "ÚLTIMO", "3.05", "EBIT", "800000.0"),
        linha(2, "000001", "ÚLTIMO", "3.01", "Receita de outra", "9.0", escala="UNIDADE", nome="OUTRA"),
    ])
    bpp = CAB + linha(1, "009999", "ÚLTIMO", "2.01.04", "Emprestimos CP", "100000.0") + \
        linha(1, "009999", "ÚLTIMO", "2.02.01", "Emprestimos LP", "900000.0")
    bpa = CAB + linha(1, "009999", "ÚLTIMO", "1.01.01", "Caixa", "50000.0") + \
        linha(1, "009999", "ÚLTIMO", "1.01.02", "Aplicacoes", "150000.0")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("dfp_cia_aberta_DRE_con_2025.csv", dre.encode("latin-1"))
        z.writestr("dfp_cia_aberta_BPP_con_2025.csv", bpp.encode("latin-1"))
        z.writestr("dfp_cia_aberta_BPA_con_2025.csv", bpa.encode("latin-1"))
    (tmp_path / "dfp_2025.zip").write_bytes(buf.getvalue())
    return tmp_path


def test_contas_usa_versao_mais_recente_e_converte_para_milhoes(zip_falso):
    c = cvm.contas("9999", 2025, "DRE", ["3.01", "3.05"])
    assert c["3.01"]["ultimo"] == pytest.approx(2000.0)     # 2.000.000 mil = R$ 2.000 mi
    assert c["3.01"]["penultimo"] == pytest.approx(1500.0)
    assert c["3.05"]["ultimo"] == pytest.approx(800.0)


def test_isola_a_empresa_pedida(zip_falso):
    assert cvm.contas("1", 2025, "DRE", ["3.01"])["3.01"]["ultimo"] == pytest.approx(9e-6)  # em unidades


def test_buscar_empresa_ignora_acento_e_caixa(zip_falso):
    r = cvm.buscar_empresa("agua", 2025)
    assert r == [{"cd_cvm": "009999", "cnpj": "11.111.111/0001-11", "nome": "EMPRESA ÁGUA S.A."}]


def test_divida_liquida(zip_falso):
    d = cvm.divida_liquida("9999", 2025)
    assert d == {"divida_bruta": pytest.approx(1000.0), "caixa": pytest.approx(200.0),
                 "divida_liquida": pytest.approx(800.0)}


def test_historico_dre_inclui_ano_anterior_pelo_penultimo(zip_falso):
    h = cvm.historico_dre("9999", 2025, anos=2)
    assert h[2025]["receita"] == pytest.approx(2000.0)
    assert h[2024]["receita"] == pytest.approx(1500.0)
    assert h[2025]["ebit"] == pytest.approx(800.0)


def test_arquivo_ausente(zip_falso):
    with pytest.raises(cvm.CvmIndisponivel):
        cvm.contas("9999", 2025, "DFC_MI", ["6.01"])
