"""Metricas de risco da carteira. Funcoes puras (numpy), sem I/O.

Convencao: `retornos` sao retornos simples por periodo (ex.: diarios, 0.01 = +1%).
VaR e ES saem como numeros POSITIVOS que representam perda (0.02 = perda de 2%).
"""

import math
from statistics import NormalDist

import numpy as np

_N = NormalDist()


def _arr(retornos) -> np.ndarray:
    r = np.asarray(retornos, dtype=float)
    if r.ndim != 1 or r.size == 0:
        raise ValueError("retornos precisa ser um vetor 1-D nao vazio")
    if not np.isfinite(r).all():
        raise ValueError("retornos contem NaN/inf")
    return r


def var_historico(retornos, nivel: float = 0.95) -> float:
    """VaR historico: perda excedida em (1 - nivel) dos periodos (quantil empirico, interpolado)."""
    r = _arr(retornos)
    return float(max(0.0, -np.quantile(r, 1.0 - nivel)))


def es_historico(retornos, nivel: float = 0.975) -> float:
    """Expected Shortfall historico: perda media nos piores (1 - nivel) dos periodos.

    Usa a media das ceil((1 - nivel) * n) piores observacoes (convencao de Basileia/FRTB).
    """
    r = np.sort(_arr(retornos))
    k = max(1, math.ceil(round((1.0 - nivel) * r.size, 10)))
    return float(max(0.0, -r[:k].mean()))


def vol_ewma(retornos, lam: float = 0.94) -> float:
    """Volatilidade por periodo (EWMA, RiskMetrics). Semente: variancia dos 20 primeiros dias."""
    r = _arr(retornos)
    semente = r[: min(20, r.size)]
    var = float(np.mean(semente ** 2))
    for x in r[min(20, r.size):]:
        var = lam * var + (1.0 - lam) * float(x) ** 2
    return math.sqrt(var)


def var_parametrico_ewma(retornos, nivel: float = 0.95, lam: float = 0.94) -> float:
    """VaR normal com volatilidade EWMA (media assumida zero, como no RiskMetrics)."""
    return _N.inv_cdf(nivel) * vol_ewma(retornos, lam)


def es_parametrico_ewma(retornos, nivel: float = 0.975, lam: float = 0.94) -> float:
    """ES normal com volatilidade EWMA: sigma * pdf(z) / (1 - nivel)."""
    z = _N.inv_cdf(nivel)
    return vol_ewma(retornos, lam) * _N.pdf(z) / (1.0 - nivel)


def kupiec_pof(excecoes: int, n: int, nivel: float = 0.95) -> tuple[float, float]:
    """Teste de Kupiec (proporcao de falhas). Retorna (estatistica LR, p-valor).

    H0: a taxa real de excecoes e (1 - nivel). p-valor baixo (< 0,05) => modelo de VaR rejeitado.
    """
    if n <= 0 or not (0 <= excecoes <= n):
        raise ValueError("excecoes/n invalidos")
    p = 1.0 - nivel
    x = excecoes
    ll0 = (n - x) * math.log(1 - p) + (x * math.log(p) if x else 0.0)
    pihat = x / n
    ll1 = 0.0
    if x < n:
        ll1 += (n - x) * math.log(1 - pihat)
    if x > 0:
        ll1 += x * math.log(pihat)
    lr = max(0.0, -2.0 * (ll0 - ll1))
    pvalor = math.erfc(math.sqrt(lr / 2.0))  # cauda do qui-quadrado com 1 g.l.
    return lr, pvalor


def backtest_var(retornos, nivel: float = 0.95, janela: int = 250) -> dict:
    """Backtest do VaR historico em janela movel: o VaR de hoje usa os `janela` retornos anteriores."""
    r = _arr(retornos)
    if r.size <= janela:
        raise ValueError(f"precisa de mais de {janela} retornos")
    excecoes = []
    for t in range(janela, r.size):
        var_t = var_historico(r[t - janela:t], nivel)
        excecoes.append(bool(r[t] < -var_t))
    n = len(excecoes)
    x = sum(excecoes)
    lr, pv = kupiec_pof(x, n, nivel)
    return {"n": n, "excecoes": x, "esperado": n * (1 - nivel), "lr": lr, "p_valor": pv,
            "rejeitado_5pct": pv < 0.05, "dias_excecao": [i + janela for i, e in enumerate(excecoes) if e]}


def contribuicao_vol(pesos, cov) -> np.ndarray:
    """Contribuicao de cada posicao para a volatilidade (soma = vol da carteira)."""
    w = np.asarray(pesos, dtype=float)
    c = np.asarray(cov, dtype=float)
    vol = math.sqrt(float(w @ c @ w))
    if vol == 0:
        return np.zeros_like(w)
    return w * (c @ w) / vol


def contribuicao_es(retornos_ativos, pesos, nivel: float = 0.975) -> np.ndarray:
    """Contribuicao de cada posicao para o ES historico (soma = ES da carteira).

    `retornos_ativos`: matriz (periodos x ativos). Usa os mesmos piores periodos da carteira.
    """
    R = np.asarray(retornos_ativos, dtype=float)
    w = np.asarray(pesos, dtype=float)
    port = R @ w
    k = max(1, math.ceil(round((1.0 - nivel) * port.size, 10)))
    piores = np.argsort(port)[:k]
    return -(R[piores] * w).mean(axis=0)


def drawdown(retornos) -> np.ndarray:
    """Serie de drawdown (<= 0) a partir dos retornos."""
    cota = np.cumprod(1.0 + _arr(retornos))
    pico = np.maximum.accumulate(np.concatenate(([1.0], cota)))[1:]
    return cota / pico - 1.0


def max_drawdown(retornos) -> float:
    return float(drawdown(retornos).min())


def semaforo(valor: float, alerta: float, limite: float) -> str:
    """OK / ATENCAO / ROMPIDO conforme o uso do limite (valor, alerta e limite na mesma unidade)."""
    if valor >= limite:
        return "ROMPIDO"
    if valor >= alerta:
        return "ATENCAO"
    return "OK"
