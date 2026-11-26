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


CAB_ITR = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;"
           "DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA\n")
CAB_BP = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;"
          "DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA\n")


def li(ref, ver, ordem, ini, fim, valor, conta="3.01"):
    return (f"11.111.111/0001-11;{ref};{ver};EMPRESA;009999;DF;REAL;MIL;{ordem};{ini};{fim};"
            f"{conta};Receita;{valor};S\n")


@pytest.fixture
def zip_itr(tmp_path, monkeypatch):
    """ITR real tem varios trimestres e, na DRE, o acumulado e o trimestre de cada um."""
    monkeypatch.setattr(cvm, "CACHE", tmp_path)
    dre = CAB_ITR + "".join([
        li("2026-06-30", 1, "ÚLTIMO", "2026-01-01", "2026-06-30", "2105003.0"),   # acumulado 1S26
        li("2026-06-30", 1, "ÚLTIMO", "2026-04-01", "2026-06-30", "1067649.0"),   # 2T26
        li("2026-06-30", 1, "PENÚLTIMO", "2025-01-01", "2025-06-30", "2244721.0"),
        li("2026-06-30", 1, "PENÚLTIMO", "2025-04-01", "2025-06-30", "1261828.0"),
        li("2026-09-30", 1, "ÚLTIMO", "2026-01-01", "2026-09-30", "2829096.0"),   # acumulado 9M26
        li("2026-09-30", 1, "ÚLTIMO", "2026-07-01", "2026-09-30", "724093.0"),    # 3T26
        li("2026-09-30", 2, "ÚLTIMO", "2026-01-01", "2026-09-30", "2830000.0"),   # reapresentacao
        li("2026-09-30", 2, "ÚLTIMO", "2026-07-01", "2026-09-30", "725000.0"),
    ])
    bpa = CAB_BP + ("11.111.111/0001-11;2026-09-30;1;EMPRESA;009999;DF;REAL;MIL;ÚLTIMO;2026-09-30;"
                    "1.01.01;Caixa;50000.0;S\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("itr_cia_aberta_DRE_con_2026.csv", dre.encode("latin-1"))
        z.writestr("itr_cia_aberta_BPA_con_2026.csv", bpa.encode("latin-1"))
    (tmp_path / "itr_2026.zip").write_bytes(buf.getvalue())
    return tmp_path


def test_itr_separa_trimestre_de_acumulado_e_pega_ultima_versao(zip_itr):
    c = cvm.contas("9999", 2026, "DRE", ["3.01"], tipo="ITR")["3.01"]
    assert c["data"] == "2026-09-30"
    assert c["ultimo"] == pytest.approx(2830.0)            # acumulado 9M, versao 2
    assert c["ultimo_trimestre"] == pytest.approx(725.0)   # so o 3T, versao 2
    assert c["ultimo_fim"] == "2026-09-30"


def test_itr_escolhe_documento_por_data(zip_itr):
    c = cvm.contas("9999", 2026, "DRE", ["3.01"], tipo="ITR", dt_refer="2026-06-30")["3.01"]
    assert c["ultimo"] == pytest.approx(2105.003)
    assert c["ultimo_trimestre"] == pytest.approx(1067.649)
    assert c["penultimo"] == pytest.approx(2244.721)
    assert c["penultimo_trimestre"] == pytest.approx(1261.828)


def test_balanco_sem_coluna_de_inicio(zip_itr):
    c = cvm.contas("9999", 2026, "BPA", ["1.01.01"], tipo="ITR")
    assert c["1.01.01"]["ultimo"] == pytest.approx(50.0)
    assert "ultimo_trimestre" not in c["1.01.01"]
