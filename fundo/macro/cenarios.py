"""Cenarios macro (bear/base/bull) a partir do modelo semiestrutural e de dados ao vivo.

Fluxo:  dados (BCB/Focus/FRED)  ->  estado inicial  ->  choques por cenario  ->  projecao.
A visao do fundo e sempre um DESVIO do consenso (Focus) com justificativa: `desvio_vs_focus`
mostra quanto o cenario-base do modelo se afasta do Focus.

Os choques e as probabilidades sao DEFINICOES (o Estrategista Macro propoe, o comite aprova);
os numeros de saida sao sempre calculados aqui, nunca escritos pelo LLM.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from fundo.macro import dados, filtros
from fundo.macro import semiestrutural_br as sm


@dataclass
class Cenario:
    nome: str                      # bear | base | bull
    probabilidade: float
    justificativa: str = ""
    choque_cambio: dict[int, float] = field(default_factory=dict)  # {trimestre(0-based): % depreciacao}
    choque_is: dict[int, float] = field(default_factory=dict)      # {trimestre: % do PIB}
    dcommodities_usd: dict[int, float] = field(default_factory=dict)  # {trimestre: pp/trim}

    def exogenas(self, n: int, add_phillips: float = 0.0) -> sm.Exogenas:
        def v(d):
            a = np.zeros(n)
            for t, x in d.items():
                if 0 <= t < n:
                    a[t] = x
            return a
        return sm.Exogenas(choque_cambio=v(self.choque_cambio), choque_is=v(self.choque_is),
                           dcommodities_usd=v(self.dcommodities_usd),
                           add_phillips=np.full(n, add_phillips))


def cenarios_padrao() -> list[Cenario]:
    """Modelos de partida (probabilidades e choques sao propostas a serem revisadas no comite)."""
    return [
        Cenario("bear", 0.25, "estresse externo/fiscal: depreciacao de 15% e demanda mais fraca",
                choque_cambio={0: 15.0}, choque_is={0: -1.0}, dcommodities_usd={0: -4.0, 1: -2.0}),
        Cenario("base", 0.55, "trajetoria do estado atual sem choques adicionais"),
        Cenario("bull", 0.20, "melhora fiscal/externa: apreciacao de 8% e demanda um pouco maior",
                choque_cambio={0: -8.0}, choque_is={0: 0.5}, dcommodities_usd={0: 2.0}),
    ]


def estado_de_dados(selic: float, selic_3m: float, ipca12: float, ipca_3m_trimestral: float,
                    exp12m: float, hiato: float, dcambio_trim: float, juro_externo: float) -> tuple[sm.Calibracao, sm.Estado]:
    """Monta (calibracao, estado) a partir de numeros ja coletados (testavel offline)."""
    cal = sm.Calibracao(juro_externo=juro_externo)
    est = sm.Estado(pi_livres=ipca_3m_trimestral, pi_adm=ipca_3m_trimestral, pi=ipca_3m_trimestral,
                    hiato=hiato, choque_is=0.0, selic=selic, selic_lag=selic_3m, exp12m=exp12m,
                    pi4q=ipca12, dif_juros=selic - juro_externo, dcambio=dcambio_trim)
    return cal, est


def hiato_trimestral(serie_mensal: list[tuple[date, float]]) -> float:
    """Hiato do ultimo trimestre COMPLETO: media trimestral do IBC-Br e filtro HP com lambda 1600
    (como o BC faz com o PIB). Trimestres incompletos no fim da serie sao descartados.
    Limitacao conhecida: o HP tem vies no fim da amostra."""
    por_tri: dict[tuple[int, int], list[float]] = {}
    for d, v in serie_mensal:
        por_tri.setdefault((d.year, (d.month - 1) // 3), []).append(v)
    medias = [sum(v) / 3 for _, v in sorted(por_tri.items()) if len(v) == 3]
    if len(medias) < 12:
        raise dados.DadosIndisponiveis("IBC-Br curto demais para estimar o hiato")
    return float(filtros.hiato_hp_percentual(medias, 1600)[-1])


def _exp12m_focus(hoje: date, data_focus: str | None = None) -> float:
    """Expectativa de IPCA para os proximos 12 meses: mistura Focus do ano corrente e do seguinte."""
    ano = hoje.year
    e0 = dados.focus_anual("IPCA", ano, data_focus)["mediana"]
    e1 = dados.focus_anual("IPCA", ano + 1, data_focus)["mediana"]
    resta = (12 - hoje.month + 1) / 12.0
    return resta * e0 + (1 - resta) * e1


def coletar(r_neutro_focus: bool = True) -> dict:
    """Coleta dados ao vivo e devolve {'cal', 'est', 'insumos'}. Levanta DadosIndisponiveis."""
    selic_s = dados.sgs(dados.SGS_SELIC_META, inicio=date.today() - timedelta(days=200))
    selic = selic_s[-1][1]
    alvo = selic_s[-1][0] - timedelta(days=90)
    selic_3m = min(selic_s, key=lambda p: abs((p[0] - alvo).days))[1]
    ipca12 = dados.sgs(dados.SGS_IPCA_12M, ultimos=1)[-1][1]
    ipca_m = [v for _, v in dados.sgs(dados.SGS_IPCA_MENSAL, ultimos=3)]
    ipca_tri = float((np.prod([1 + x / 100 for x in ipca_m]) - 1) * 100)
    cambio = dados.sgs(dados.SGS_CAMBIO_VENDA, inicio=date.today() - timedelta(days=150))
    ult = cambio[-1]
    ref = min(cambio, key=lambda p: abs((p[0] - (ult[0] - timedelta(days=90))).days))
    dcambio = (ult[1] / ref[1] - 1) * 100
    ibc = dados.sgs(dados.SGS_IBC_BR, inicio=date(2005, 1, 1))
    hiato = hiato_trimestral(ibc)
    exp12m = _exp12m_focus(selic_s[-1][0])
    ff = dados.fred("DFF", inicio=(date.today() - timedelta(days=30)).isoformat())[-1][1]
    cal, est = estado_de_dados(selic, selic_3m, ipca12, ipca_tri, exp12m, hiato, dcambio, ff)
    if r_neutro_focus:  # juro real de longo prazo implicito no Focus (Selic - IPCA, ultimo ano disponivel)
        ano = selic_s[-1][0].year + 2
        try:
            rn = dados.focus_selic_fim_de_ano(ano) - dados.focus_anual("IPCA", ano)["mediana"]
            cal = sm.Calibracao(juro_neutro=float(rn), juro_externo=ff)
        except dados.DadosIndisponiveis:
            pass
    insumos = {"selic": selic, "ipca12": ipca12, "ipca_trimestre": ipca_tri, "exp12m": exp12m,
               "hiato_ibc_hp": hiato, "dcambio_90d": dcambio, "fed_funds": ff,
               "juro_neutro": cal.juro_neutro}
    return {"cal": cal, "est": est, "insumos": insumos}


def ancorar_no_focus(cal: sm.Calibracao, est: sm.Estado, ipca_alvo_4q: float, horizonte: int = 4) -> float:
    """Fator de ajuste aditivo constante na Phillips (pp por trimestre) que faz o cenario-base
    reproduzir o IPCA acumulado do consenso no horizonte. Pratica padrao de bancos centrais
    (add-factors): o modelo sozinho nao carrega choques persistentes ja em curso.
    Resolve por bissecao (a resposta e monotona no fator)."""
    n = cal.n_trimestres

    def f(c):
        r = sm.simular(cal, est, sm.Exogenas(add_phillips=np.full(n, c)))
        return float(r["pi4q"][horizonte - 1]) - ipca_alvo_4q

    lo, hi = -3.0, 3.0
    if f(lo) > 0 or f(hi) < 0:
        raise ValueError("ancora fora do intervalo plausivel; revise os insumos")
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return (lo + hi) / 2


def projetar(cal: sm.Calibracao, est: sm.Estado, cenarios: list[Cenario] | None = None,
             ancora: float = 0.0) -> dict:
    """Projeta cada cenario e a media ponderada por probabilidade (horizontes 4 e 8 trimestres)."""
    cenarios = cenarios or cenarios_padrao()
    soma = sum(c.probabilidade for c in cenarios)
    if abs(soma - 1.0) > 1e-6:
        raise ValueError(f"probabilidades somam {soma:.3f}, devem somar 1")
    n = cal.n_trimestres
    resultado: dict = {"cenarios": {}, "ponderado": {}, "ancora_phillips": ancora}
    res = {}
    for c in cenarios:
        r = sm.simular(cal, est, c.exogenas(n, ancora))
        res[c.nome] = r
        resultado["cenarios"][c.nome] = {
            "probabilidade": c.probabilidade, "justificativa": c.justificativa,
            **{f"h{h}": {"ipca_4q": float(r["pi4q"][h - 1]), "selic": float(r["selic"][h - 1]),
                         "cambio_nominal_pct": float(r["cambio_nominal_acum"][h - 1]),
                         "cambio_real_pct": float(r["cambio_acum"][h - 1]), "hiato": float(r["hiato"][h - 1])}
               for h in (4, 8)}}
    for h in (4, 8):
        resultado["ponderado"][f"h{h}"] = {
            k: float(sum(c.probabilidade * res[c.nome][kk][h - 1] for c in cenarios))
            for k, kk in (("ipca_4q", "pi4q"), ("selic", "selic"), ("cambio_nominal_pct", "cambio_nominal_acum"),
                          ("cambio_real_pct", "cambio_acum"), ("hiato", "hiato"))}
    return resultado


def desvio_vs_focus(proj: dict, selic_focus_1a: float, ipca_focus_1a: float) -> dict:
    """Quanto o cenario-base (horizonte 4 trimestres) se afasta do consenso Focus."""
    b = proj["cenarios"]["base"]["h4"]
    return {"ipca_modelo": b["ipca_4q"], "ipca_focus": ipca_focus_1a, "desvio_ipca_pp": b["ipca_4q"] - ipca_focus_1a,
            "selic_modelo": b["selic"], "selic_focus": selic_focus_1a, "desvio_selic_pp": b["selic"] - selic_focus_1a}
