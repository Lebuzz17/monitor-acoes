"""Filtros de tendencia/ciclo (numpy puro)."""

import numpy as np


def hp_filter(y, lamb: float = 1600.0) -> tuple[np.ndarray, np.ndarray]:
    """Filtro Hodrick-Prescott. Retorna (tendencia, ciclo).

    lamb: 1600 trimestral (o BC usa 1600 para PIB), 129600 mensal.
    Resolve (I + lamb * K'K) tau = y com K = matriz de segunda diferenca.
    """
    y = np.asarray(y, dtype=float)
    n = y.size
    if n < 4:
        raise ValueError("serie curta demais para o filtro HP")
    K = np.zeros((n - 2, n))
    for i in range(n - 2):
        K[i, i:i + 3] = (1.0, -2.0, 1.0)
    tau = np.linalg.solve(np.eye(n) + lamb * K.T @ K, y)
    return tau, y - tau


def hiato_hp_percentual(nivel, lamb: float = 1600.0) -> np.ndarray:
    """Hiato (% da tendencia) de uma serie em nivel positivo, via HP no log."""
    logy = np.log(np.asarray(nivel, dtype=float))
    _, ciclo = hp_filter(logy, lamb)
    return 100.0 * ciclo
