"""Placar da eleicao semanal: escolhe a empresa de maior retorno esperado ajustado.

Tudo em codigo. Entradas por candidata: modelo em rascunho (alvos, confianca 1-5), preco atual,
nivel de dificuldade da empresa e dados de concentracao/liquidez. O placar:
  1. retorno esperado anualizado = (alvo base / preco)^(1/horizonte) - 1  (horizonte = 1 ano)
  2. fator de confianca (nota 1-5)
  3. filtro do curriculo: empresa acima do nivel da semana fica fora do pool
  4. penalidades: concentracao (peso/setor perto do limite), liquidez, aprovada recentemente
  5. alerta automatico para retorno acima do teto (suspeita de dado errado/ciclo no pico)
"""

from dataclasses import dataclass, field

TETO_RETORNO_ALERTA = 0.60
HORIZONTE_ANOS = 1.0
FATOR_CONFIANCA = {1: 0.50, 2: 0.65, 3: 0.80, 4: 0.90, 5: 1.00}


@dataclass
class Candidata:
    ticker: str
    alvo_base: float
    alvo_bear: float
    alvo_bull: float
    preco: float
    confianca: int                       # 1 a 5
    nivel_dificuldade: int = 1
    uso_limite_setor: float = 0.0        # 0..1+  (peso do setor / limite do setor)
    dias_para_zerar: float = 0.0
    dias_desde_aprovacao: int | None = None   # None = nunca aprovada


@dataclass
class Resultado:
    ticker: str
    retorno_anual: float
    score: float
    elegivel: bool
    alertas: list[str] = field(default_factory=list)
    motivos_exclusao: list[str] = field(default_factory=list)


def retorno_esperado(alvo_base: float, preco: float, anos: float = HORIZONTE_ANOS) -> float:
    if preco <= 0 or alvo_base <= 0:
        raise ValueError("preco e alvo devem ser positivos")
    return (alvo_base / preco) ** (1.0 / anos) - 1.0


def pontuar(c: Candidata, nivel_curriculo: int, limite_liquidez_dias: float = 5.0,
            recente_dias: int = 90) -> Resultado:
    if c.confianca not in FATOR_CONFIANCA:
        raise ValueError("confianca deve ser 1..5")
    r = retorno_esperado(c.alvo_base, c.preco)
    res = Resultado(c.ticker, r, 0.0, True)
    if r <= 0:
        res.elegivel = False
        res.motivos_exclusao.append(f"retorno esperado nao positivo ({r:.1%})")
    if c.nivel_dificuldade > nivel_curriculo:
        res.elegivel = False
        res.motivos_exclusao.append(f"nivel de dificuldade {c.nivel_dificuldade} acima do nivel {nivel_curriculo} da semana")
    if c.dias_para_zerar > limite_liquidez_dias:
        res.elegivel = False
        res.motivos_exclusao.append(f"liquidez: {c.dias_para_zerar:.1f} dias para zerar (limite {limite_liquidez_dias})")
    if c.uso_limite_setor >= 1.0:
        res.elegivel = False
        res.motivos_exclusao.append("setor ja no limite de peso da politica")
    if r > TETO_RETORNO_ALERTA:
        res.alertas.append(f"retorno esperado {r:.0%} acima do teto de {TETO_RETORNO_ALERTA:.0%}: revisar dado/ciclo")
    if not (c.alvo_bear <= c.alvo_base <= c.alvo_bull):
        res.alertas.append("alvos fora de ordem (bear <= base <= bull)")
    score = r * FATOR_CONFIANCA[c.confianca]
    if c.uso_limite_setor > 0.8:       # perto do limite: desconto proporcional
        score *= 1.0 - (c.uso_limite_setor - 0.8) * 2.5   # 0.8 -> 0%, 1.0 -> -50%
    if c.dias_desde_aprovacao is not None and c.dias_desde_aprovacao < recente_dias:
        score *= 0.5
        res.alertas.append("aprovada recentemente: penalizada")
    res.score = score
    return res


def eleger(candidatas: list[Candidata], nivel_curriculo: int, n: int = 1) -> dict:
    """Ranqueia o pool elegivel. Retorna {'eleitas': [...], 'ranking': [...], 'excluidas': [...]}."""
    pontuadas = [pontuar(c, nivel_curriculo) for c in candidatas]
    pool = sorted((p for p in pontuadas if p.elegivel), key=lambda p: p.score, reverse=True)
    return {"eleitas": pool[:n], "ranking": pool, "excluidas": [p for p in pontuadas if not p.elegivel]}
