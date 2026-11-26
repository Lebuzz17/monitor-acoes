"""Liquidez: dias para zerar cada posicao participando de uma fracao do volume diario."""

import math


def dias_para_zerar(quantidade: float, volume_medio_diario: float, participacao: float = 0.20) -> float:
    """Dias para vender `quantidade` se so puder negociar `participacao` do volume medio diario.

    Volume zero/ausente => infinito (posicao nao liquidavel pelo dado disponivel).
    """
    if quantidade < 0 or not (0 < participacao <= 1):
        raise ValueError("quantidade >= 0 e 0 < participacao <= 1")
    if quantidade == 0:
        return 0.0
    if not volume_medio_diario or volume_medio_diario <= 0:
        return math.inf
    return quantidade / (participacao * volume_medio_diario)


def relatorio_liquidez(posicoes: dict[str, float], volumes: dict[str, float],
                       participacao: float = 0.20, limite_dias: float = 5.0) -> dict:
    """posicoes/volumes na mesma unidade (ex.: R$ ou numero de papeis).

    Retorna dias por ativo, o pior caso, e quais violam o limite da politica.
    """
    dias = {a: dias_para_zerar(q, volumes.get(a, 0.0), participacao) for a, q in posicoes.items()}
    violam = sorted(a for a, d in dias.items() if d > limite_dias)
    return {"dias": dias, "pior": max(dias.values(), default=0.0), "violam_limite": violam,
            "limite_dias": limite_dias, "participacao": participacao}
