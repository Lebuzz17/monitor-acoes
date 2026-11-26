"""Modelo semiestrutural de pequeno porte (versao agregada) do Banco Central do Brasil.

Fonte dos parametros: BCB, Relatorio de Inflacao de junho de 2024, boxe "Atualizacao dos
modelos semiestruturais de pequeno porte", Tabela 1 (modas a posteriori, amostra 2003T4-2023T4).
https://www.bcb.gov.br/content/ri/relatorioinflacao/202406/ri202406b12p.pdf

ATENCAO - o que e do BC e o que e reconstrucao nossa:
  * Os COEFICIENTES (alfa, beta, theta, phi, delta) sao os publicados pelo BC.
  * As EQUACOES aparecem como imagem no PDF; a forma abaixo segue o texto do boxe e foi
    conferida contra as respostas ao impulso que o proprio BC publica (ver tests/test_macro.py).
  * O bloco de PRECOS ADMINISTRADOS NAO e publicado nesse boxe (o BC usa modelos a parte);
    usamos uma forma reduzida calibrada por nos para reproduzir o repasse cambial do boxe.
  * Hiato do produto e uma variavel nao observavel no BC (filtro de Kalman com 4 indicadores);
    aqui ele e dado de entrada (estimativa externa) ou vem de um filtro HP sobre o IBC-Br.
  * Nao ha termo de clima (El Nino/La Nina), IPPCV nem expectativas de Selic endogenas alem
    da regra de Taylor: sao omitidos (efeito de curto prazo, nao estrutural).

Aderencia as respostas ao impulso publicadas pelo BC (IPCA acumulado em 4 trimestres, modelo
agregado; ver tests/test_macro.py):
    cambio +10%           BC +0,96 p.p. | aqui +0,87  (-9%)
    hiato +1%             BC +0,49 p.p. | aqui +0,53  (+8%)
    Selic +1 p.p. x 4 tri BC -0,27 p.p. | aqui -0,47  (1,7x: sinal e ordem de grandeza certos,
                                                      efeito dos juros superestimado)
Divergencia residual provavel: expectativa de Selic (aqui, previsao perfeita da trajetoria
imposta; no BC vem da Focus) e componentes omitidos. Use o modelo para direcao e ordem de
grandeza de cenarios, nao para previsao pontual.

Unidades: periodicidade TRIMESTRAL. Inflacoes em % por trimestre; juros, expectativas e
metas em % ao ano; hiato em % do PIB; variacao cambial em % por trimestre (+ = depreciacao).
Expectativas consistentes com o modelo e Selic esperada em 12 meses sao forward-looking:
resolvemos por iteracao de ponto fixo.
"""

from dataclasses import dataclass, field, replace

import numpy as np

# --- Parametros publicados (Tabela 1, modelo agregado, moda a posteriori) ----------------
ALPHA1L = 0.24   # inercia da inflacao de livres
ALPHA1I = 0.38   # inercia da inflacao IPCA
ALPHA2 = 0.023   # inflacao importada (commodities em R$, desvio da meta)
ALPHA3 = 0.011   # variacao do cambio (1 defasagem, desvio da PPC)
ALPHA4 = 0.120   # hiato do produto
BETA1 = 0.85     # autorregressivo da IS
BETA2 = 0.44     # juro real (hiato de juros)
BETA3 = 0.030    # resultado primario
BETA4 = 0.054    # hiato mundial
BETA5 = 0.84     # autorregressivo do choque da IS
THETA1 = 1.48    # suavizacao dos juros, 1a defasagem
THETA2 = -0.58   # suavizacao dos juros, 2a defasagem
THETA3 = 2.03    # resposta da Selic ao desvio da expectativa em relacao a meta
PHI1 = 0.75      # inercia das expectativas
PHI2 = 0.11      # expectativa consistente com o modelo
PHI3 = 0.021     # inflacao passada
DELTA = 1.90     # diferencial de juros interno-externo (UIP)

# --- Calibracao nossa (nao publicada no boxe) --------------------------------------------
PESO_LIVRES = 0.75         # IPCA = 0,75 livres + 0,25 administrados (consistente com o boxe)
ADM_INERCIA = 0.5          # persistencia da inflacao de administrados
# Especificacao (as equacoes sao imagem no PDF; escolhida para reproduzir as IRFs do boxe)
PHILLIPS_HIATO_DEFASAGEM = 1   # 0 = h_t ; 1 = h_{t-1}  (1 reproduz melhor as IRFs do boxe)
IS_GAP_JANELA = 1              # media do hiato de juros reais nos ultimos N trimestres
ADM_CAMBIO0 = 0.047       # repasse cambial contemporaneo aos administrados
ADM_CAMBIO1 = 0.047        # repasse cambial com 1 trimestre de defasagem


@dataclass(frozen=True)
class Calibracao:
    """Valores de equilibrio / ambiente. Tudo em % a.a. (exceto onde dito)."""
    meta: float = 3.0            # meta de inflacao (doméstica)
    juro_neutro: float = 4.5     # juro real neutro r* (%)
    meta_externa: float = 2.0    # inflacao de equilibrio externa
    juro_externo: float = 3.5    # Fed Funds (nivel; so a variacao importa na UIP)
    n_trimestres: int = 20


@dataclass
class Estado:
    """Condicoes iniciais (valores observados no trimestre anterior ao primeiro simulado)."""
    pi_livres: float = 0.75      # % no trimestre
    pi_adm: float = 0.75
    pi: float = 0.75             # IPCA, % no trimestre
    hiato: float = 0.0
    choque_is: float = 0.0
    selic: float = 7.5           # % a.a. (t-1)
    selic_lag: float = 7.5       # (t-2)
    exp12m: float = 3.0          # expectativa Focus de IPCA 12m (% a.a.)
    pi4q: float = 3.0            # IPCA acumulado em 4 trimestres (% a.a.)
    dif_juros: float = 4.0       # selic - juro externo (t-1)
    dcambio: float = 0.25        # variacao cambial no trimestre t-1 (% )


@dataclass
class Exogenas:
    """Trajetorias exogenas (vetores de tamanho n; None = zero/equilibrio)."""
    choque_cambio: np.ndarray | None = None      # depreciacao adicional, % no trimestre
    dcommodities_usd: np.ndarray | None = None   # desvio da inflacao de commodities em US$ (pp/trim.)
    choque_is: np.ndarray | None = None          # choque de demanda no hiato (% do PIB)
    hiato_mundial: np.ndarray | None = None
    fiscal: np.ndarray | None = None
    juro_externo: np.ndarray | None = None       # nivel do juro externo (% a.a.)
    selic_imposta: np.ndarray | None = None      # NaN = regra de Taylor; valor = Selic fixada
    add_phillips: np.ndarray | None = None       # fator de ajuste aditivo na Phillips (pp/trim.), p/ ancorar no consenso


def _v(x, n, padrao=0.0):
    if x is None:
        return np.full(n, padrao, dtype=float)
    a = np.asarray(x, dtype=float)
    if a.shape != (n,):
        raise ValueError(f"vetor com tamanho {a.shape}, esperado ({n},)")
    return a


def simular(cal: Calibracao, est: Estado, exo: Exogenas | None = None, iteracoes: int = 60) -> dict:
    """Simula n trimestres. Retorna dict de vetores (pi, pi_livres, pi_adm, hiato, selic, exp12m,
    dcambio, cambio_acum, pi4q, choque_is)."""
    exo = exo or Exogenas()
    n = cal.n_trimestres
    T, Tq = cal.meta, cal.meta / 4.0
    dppp = (cal.meta - cal.meta_externa) / 4.0           # depreciacao de PPC por trimestre
    r_star = cal.juro_neutro
    ch_cam = _v(exo.choque_cambio, n)
    dcom = _v(exo.dcommodities_usd, n)
    ch_is = _v(exo.choque_is, n)
    hw = _v(exo.hiato_mundial, n)
    fisc = _v(exo.fiscal, n)
    i_ext = _v(exo.juro_externo, n, cal.juro_externo)
    imposta = np.full(n, np.nan) if exo.selic_imposta is None else _v(exo.selic_imposta, n, np.nan)
    add_ph = _v(exo.add_phillips, n)
    dcom_base = Tq - dppp  # em equilibrio, commodities em R$ sobem a meta

    pi_path = np.full(n, Tq)
    selic_path = np.full(n, est.selic)
    out: dict = {}
    for _ in range(iteracoes):
        o = {k: np.zeros(n) for k in
             ("pi", "pi_livres", "pi_adm", "hiato", "selic", "exp12m", "dcambio", "pi4q", "choque_is")}
        pi_prev, pl_prev, pa_prev = est.pi, est.pi_livres, est.pi_adm
        h_prev, u_prev = est.hiato, est.choque_is
        i1, i2 = est.selic, est.selic_lag
        E_prev, dif_prev, dcam_prev = est.exp12m, est.dif_juros, est.dcambio
        hist_pi = [est.pi4q / 4.0] * 3 + [est.pi]          # ultimos trimestres de IPCA
        hist_pl = [est.pi_livres] * 4                       # ultimos trimestres de livres
        gaps: list = []
        h_hist = [est.hiato]
        for t in range(n):
            fut = pi_path[t + 1:t + 5]
            fut = np.concatenate([fut, np.full(4 - fut.size, Tq)])
            em = float(fut.sum())                           # expectativa consistente (4 trimestres)
            passado = float(sum(hist_pi[-4:]))
            E = PHI1 * E_prev + PHI2 * em + PHI3 * passado + (1 - PHI1 - PHI2 - PHI3) * T
            fut_i = selic_path[t:t + 4]
            sel12 = float(np.concatenate([fut_i, np.full(4 - fut_i.size, selic_path[-1])]).mean())
            gap = sel12 - E - r_star                        # hiato de juros reais ex-ante
            u = BETA5 * u_prev + ch_is[t]
            gap_ef = float(np.mean(gaps[-IS_GAP_JANELA:])) if gaps else gap
            h = BETA1 * h_prev - BETA2 * gap_ef + BETA4 * hw[t] + BETA3 * fisc[t] + u
            taylor = THETA1 * i1 + THETA2 * i2 + (1 - THETA1 - THETA2) * (r_star + T + THETA3 * (E - T))
            i = float(imposta[t]) if not np.isnan(imposta[t]) else taylor
            dif = i - i_ext[t]
            dcam = dppp + ch_cam[t] - DELTA * (dif - dif_prev)
            pi_ic = dcam + dcom_base + dcom[t]
            # inercia = media dos 4 trimestres anteriores (como nas curvas setoriais do boxe)
            pl = (ALPHA1L * float(np.mean(hist_pl[-4:])) + ALPHA1I * float(np.mean(hist_pi[-4:]))
                  + (1 - ALPHA1L - ALPHA1I) * E / 4.0
                  + ALPHA2 * (pi_ic - Tq) + ALPHA3 * (dcam_prev - dppp) + ALPHA4 * (h if PHILLIPS_HIATO_DEFASAGEM == 0 else h_hist[-1]) + add_ph[t])
            pa = (ADM_INERCIA * pa_prev + (1 - ADM_INERCIA) * Tq
                  + ADM_CAMBIO0 * (dcam - dppp) + ADM_CAMBIO1 * (dcam_prev - dppp))
            p = PESO_LIVRES * pl + (1 - PESO_LIVRES) * pa
            hist_pi.append(p)
            hist_pl.append(pl)
            for k, val in (("pi", p), ("pi_livres", pl), ("pi_adm", pa), ("hiato", h), ("selic", i),
                           ("exp12m", E), ("dcambio", dcam), ("pi4q", sum(hist_pi[-4:]) ), ("choque_is", u)):
                o[k][t] = val
            pi_prev, pl_prev, pa_prev, h_prev, u_prev = p, pl, pa, h, u
            h_hist.append(h)
            gaps.append(gap)
            i2, i1, E_prev, dif_prev, dcam_prev = i1, i, E, dif, dcam
        mudou = float(np.abs(o["pi"] - pi_path).max() + np.abs(o["selic"] - selic_path).max())
        pi_path, selic_path, out = o["pi"].copy(), o["selic"].copy(), o
        if mudou < 1e-10:
            break
    out["cambio_acum"] = np.cumsum(out["dcambio"] - dppp)
    return out


def equilibrio(cal: Calibracao) -> Estado:
    """Estado estacionario consistente com a calibracao (inflacao na meta, hiato zero)."""
    Tq = cal.meta / 4.0
    i = cal.juro_neutro + cal.meta
    dppp = (cal.meta - cal.meta_externa) / 4.0
    return Estado(pi_livres=Tq, pi_adm=Tq, pi=Tq, hiato=0.0, choque_is=0.0, selic=i, selic_lag=i,
                  exp12m=cal.meta, pi4q=cal.meta, dif_juros=i - cal.juro_externo, dcambio=dppp)


def resposta_ao_impulso(cal: Calibracao | None = None, choque: str = "selic") -> dict:
    """Resposta (desvio do equilibrio) a choques-padrao do boxe do BC.

    'selic'  : Selic +1 p.p. por 4 trimestres, depois regra de Taylor.
    'cambio' : depreciacao permanente de 10% (em um trimestre).
    'hiato'  : choque de demanda de +1% no hiato do produto.
    """
    cal = cal or Calibracao()
    est = equilibrio(cal)
    base = simular(cal, est)
    n = cal.n_trimestres
    if choque == "selic":
        imp = np.full(n, np.nan)
        imp[:4] = est.selic + 1.0
        res = simular(cal, est, Exogenas(selic_imposta=imp))
    elif choque == "cambio":
        c = np.zeros(n); c[0] = 10.0
        res = simular(cal, est, Exogenas(choque_cambio=c))
    elif choque == "hiato":
        c = np.zeros(n); c[0] = 1.0
        res = simular(cal, est, Exogenas(choque_is=c))
    else:
        raise ValueError("choque desconhecido")
    return {k: res[k] - base[k] for k in res}
