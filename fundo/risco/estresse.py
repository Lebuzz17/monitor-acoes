"""Testes de estresse: hipoteticos (choques dados) e historicos (episodios medidos nos dados).

Nenhum numero de episodio e escrito a mao aqui: os retornos dos fatores em cada janela
historica sao CALCULADOS a partir de series de precos que o chamador fornece (yfinance etc.).
"""

import numpy as np

# Choques hipoteticos do plano (variaveis em % sobre o fator indicado)
HIPOTETICOS_PADRAO = {
    "BRL +20% (USD/BRL sobe 20%)": {"USDBRL": +20.0},
    "Selic +300bp": {"SELIC_BP": +300.0},
    "BTC -50%": {"BTC": -50.0},
}


def betas_ols(retornos_ativo, retornos_fatores: dict[str, np.ndarray]) -> dict[str, float]:
    """Betas por minimos quadrados (com intercepto) de um ativo/carteira contra os fatores."""
    y = np.asarray(retornos_ativo, dtype=float)
    nomes = list(retornos_fatores)
    X = np.column_stack([np.ones(y.size)] + [np.asarray(retornos_fatores[k], float) for k in nomes])
    if X.shape[0] <= X.shape[1]:
        raise ValueError("observacoes insuficientes para a regressao")
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return {k: float(c) for k, c in zip(nomes, coef[1:])}


def estresse_hipotetico(pesos: dict[str, float], sensibilidades: dict[str, dict[str, float]],
                        choques: dict[str, float]) -> dict:
    """Perda da carteira sob um choque.

    pesos: {ativo: peso na carteira}.
    sensibilidades: {ativo: {fator: beta}} (retorno do ativo por 1% de variacao do fator).
    choques: {fator: variacao em %}. Retorna {'pnl_pct': ..., 'por_ativo': {ativo: contribuicao %}}.
    """
    por_ativo = {}
    for ativo, w in pesos.items():
        ret = sum(beta * choques.get(f, 0.0) for f, beta in sensibilidades.get(ativo, {}).items())
        por_ativo[ativo] = w * ret
    return {"pnl_pct": float(sum(por_ativo.values())), "por_ativo": por_ativo}


def retorno_na_janela(precos, inicio: int, fim: int) -> float:
    """Retorno acumulado (%) entre os indices inicio e fim (inclusive) de uma serie de precos."""
    p = np.asarray(precos, dtype=float)
    return (p[fim] / p[inicio] - 1.0) * 100.0


def pior_janela(precos, dias: int) -> tuple[int, int, float]:
    """Pior queda acumulada em `dias` pregoes: (inicio, fim, retorno %). Define episodios sem subjetividade."""
    p = np.asarray(precos, dtype=float)
    if p.size <= dias:
        raise ValueError("serie curta demais")
    ret = p[dias:] / p[:-dias] - 1.0
    i = int(np.argmin(ret))
    return i, i + dias, float(ret[i] * 100.0)


def estresse_historico(pesos: dict[str, float], precos_ativos: dict[str, np.ndarray],
                       janela: tuple[int, int]) -> dict:
    """Reaplica a janela historica (indices comuns) sobre a carteira atual, ativo a ativo."""
    por_ativo = {a: w * retorno_na_janela(precos_ativos[a], *janela) for a, w in pesos.items()
                 if a in precos_ativos}
    ausentes = [a for a in pesos if a not in precos_ativos]
    return {"pnl_pct": float(sum(por_ativo.values())), "por_ativo": por_ativo, "sem_historico": ausentes}
