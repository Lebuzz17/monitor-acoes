"""Motor de DCF (FCFF) em Python puro: o 'calculo paralelo' que confere cada Excel.

O Excel gerado pelo builder usa FORMULAS reais; este modulo calcula o mesmo modelo em
codigo. Depois do recalculo no LibreOffice, os dois precisam bater (ver recalc.conferir).
Se divergirem, o Excel esta com erro de formula e nao pode virar alvo.

Valores monetarios em R$ milhoes (ou US$ milhoes), acoes em milhoes, taxas em fracao (0,05 = 5%).
Convencao de desconto: fluxos no FIM de cada ano; valor terminal por Gordon sobre FCFF_N.
"""

from dataclasses import dataclass, field, replace

CENARIOS = ("bear", "base", "bull")


@dataclass(frozen=True)
class Premissas:
    receita_base: float                 # receita do ultimo ano realizado
    crescimento: tuple[float, ...]      # por ano projetado
    margem_ebitda: tuple[float, ...]
    da_pct: tuple[float, ...]           # D&A como % da receita
    capex_pct: tuple[float, ...]        # capex como % da receita
    nwc_pct: float                      # variacao de capital de giro = nwc_pct * variacao da receita
    aliquota_ir: float
    rf: float                           # taxa livre de risco (na moeda do fluxo)
    erp: float                          # premio de risco de mercado
    beta: float
    kd_pre: float                       # custo da divida antes do imposto
    peso_divida: float                  # D / (D + E) alvo
    g_terminal: float
    divida_liquida: float
    acoes: float                        # milhoes
    preco_atual: float
    ano_base: int = 2026

    def __post_init__(self):
        n = len(self.crescimento)
        if n < 1 or not (len(self.margem_ebitda) == len(self.da_pct) == len(self.capex_pct) == n):
            raise ValueError("vetores anuais precisam ter o mesmo tamanho (>= 1)")
        if not (0 <= self.peso_divida < 1) or not (0 <= self.aliquota_ir < 1):
            raise ValueError("peso_divida e aliquota_ir devem estar em [0, 1)")
        if self.acoes <= 0 or self.receita_base <= 0 or self.preco_atual <= 0:
            raise ValueError("acoes, receita_base e preco_atual devem ser positivos")

    @property
    def n(self) -> int:
        return len(self.crescimento)


def wacc(p: Premissas) -> tuple[float, float, float]:
    """(Ke, Kd liquido, WACC)."""
    ke = p.rf + p.beta * p.erp
    kd = p.kd_pre * (1 - p.aliquota_ir)
    return ke, kd, (1 - p.peso_divida) * ke + p.peso_divida * kd


def projetar(p: Premissas) -> dict:
    """Projecao ano a ano. Retorna dict de listas (indice 0 = ano 1)."""
    rec, ebitda, da, ebit, ir, nopat, capex, dnwc, fcff = ([] for _ in range(9))
    anterior = p.receita_base
    for t in range(p.n):
        r = anterior * (1 + p.crescimento[t])
        e = r * p.margem_ebitda[t]
        d = r * p.da_pct[t]
        b = e - d
        i = b * p.aliquota_ir
        n_ = b - i
        cx = r * p.capex_pct[t]
        dn = p.nwc_pct * (r - anterior)
        rec.append(r); ebitda.append(e); da.append(d); ebit.append(b); ir.append(i)
        nopat.append(n_); capex.append(cx); dnwc.append(dn)
        fcff.append(n_ + d - cx - dn)
        anterior = r
    return {"receita": rec, "ebitda": ebitda, "da": da, "ebit": ebit, "ir": ir, "nopat": nopat,
            "capex": capex, "dnwc": dnwc, "fcff": fcff}


def valuation(p: Premissas) -> dict:
    ke, kd, w = wacc(p)
    if w <= p.g_terminal:
        raise ValueError(f"WACC ({w:.4f}) deve ser maior que g terminal ({p.g_terminal:.4f})")
    pr = projetar(p)
    vp = [f / (1 + w) ** (t + 1) for t, f in enumerate(pr["fcff"])]
    fcff_term = pr["fcff"][-1] * (1 + p.g_terminal)
    vt = fcff_term / (w - p.g_terminal)
    vp_vt = vt / (1 + w) ** p.n
    ev = sum(vp) + vp_vt
    equity = ev - p.divida_liquida
    por_acao = equity / p.acoes
    return {"ke": ke, "kd_liq": kd, "wacc": w, "projecao": pr, "vp_fcff": vp, "soma_vp": sum(vp),
            "fcff_terminal": fcff_term, "vt": vt, "vp_vt": vp_vt, "ev": ev, "equity": equity,
            "valor_por_acao": por_acao, "upside": por_acao / p.preco_atual - 1.0,
            "peso_vt": vp_vt / ev if ev else float("nan")}


def sensibilidade(p: Premissas, deltas_wacc=(-0.02, -0.01, 0.0, 0.01, 0.02),
                  gs=(0.02, 0.03, 0.04, 0.05)) -> dict:
    """Valor por acao para combinacoes de WACC (absoluto = base + delta) e g terminal."""
    base_w = wacc(p)[2]
    pr = projetar(p)["fcff"]
    grade = {}
    for dw in deltas_wacc:
        w = base_w + dw
        for g in gs:
            if w <= g:
                grade[(dw, g)] = None
                continue
            vp = sum(f / (1 + w) ** (t + 1) for t, f in enumerate(pr))
            vt = pr[-1] * (1 + g) / (w - g) / (1 + w) ** len(pr)
            grade[(dw, g)] = (vp + vt - p.divida_liquida) / p.acoes
    return grade


def alvo_ponderado(resultados: dict[str, dict], probabilidades: dict[str, float]) -> float:
    if abs(sum(probabilidades.values()) - 1.0) > 1e-9:
        raise ValueError("probabilidades devem somar 1")
    return sum(probabilidades[c] * resultados[c]["valor_por_acao"] for c in resultados)


def ipca_anual_de_cenario(pi4q, anos: int) -> list[float]:
    """IPCA anual (fracao) por ano projetado a partir do vetor `pi4q` (% acumulado em 4 trimestres)
    do modelo macro: usa o valor do 4o trimestre de cada ano."""
    if len(pi4q) < 4 * anos:
        raise ValueError("horizonte do modelo macro menor que o horizonte do DCF")
    return [float(pi4q[4 * a + 3]) / 100.0 for a in range(anos)]
