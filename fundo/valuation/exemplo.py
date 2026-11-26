"""Empresa FICTICIA ("Exemplo Transmissao SA") usada em testes e para mostrar o formato do Excel.

Todos os numeros sao inventados para teste: NAO representam nenhuma empresa real e nao devem
ser usados em decisao. Fontes marcadas como EXEMPLO.
"""

from fundo.valuation import dcf

N = 5


def premissas_exemplo() -> tuple[dict[str, dcf.Premissas], dict[str, float], dict[str, dict]]:
    base = dcf.Premissas(
        receita_base=1000.0,
        crescimento=(0.050, 0.045, 0.045, 0.040, 0.040),
        margem_ebitda=(0.80,) * N,
        da_pct=(0.12,) * N,
        capex_pct=(0.14, 0.14, 0.13, 0.13, 0.12),
        nwc_pct=0.05,
        aliquota_ir=0.34,
        rf=0.115, erp=0.055, beta=0.65, kd_pre=0.125, peso_divida=0.40,
        g_terminal=0.035,
        divida_liquida=2500.0, acoes=100.0, preco_atual=30.0, ano_base=2026)
    bear = dcf.Premissas(**{**base.__dict__, "crescimento": (0.030, 0.030, 0.030, 0.030, 0.030),
                            "margem_ebitda": (0.76,) * N, "beta": 0.80, "g_terminal": 0.030})
    bull = dcf.Premissas(**{**base.__dict__, "crescimento": (0.065, 0.060, 0.055, 0.050, 0.050),
                            "margem_ebitda": (0.82,) * N, "beta": 0.60, "g_terminal": 0.040})
    probs = {"bear": 0.25, "base": 0.55, "bull": 0.20}
    doc = {"fonte": "EXEMPLO - documento ficticio", "trecho": "EXEMPLO - trecho ficticio", "data": "2026-01-01"}
    chaves = ["ano_base", "receita_base", "nwc_pct", "aliquota_ir", "rf", "erp", "beta", "kd_pre",
              "peso_divida", "g_terminal", "divida_liquida", "acoes", "preco_atual", "probabilidade",
              "crescimento", "margem_ebitda", "da_pct", "capex_pct"]
    return {"bear": bear, "base": base, "bull": bull}, probs, {k: dict(doc) for k in chaves}
