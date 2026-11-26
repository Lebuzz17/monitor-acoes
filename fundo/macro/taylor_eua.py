"""Regra de Taylor dos EUA: juro 'justo' contra Fed Funds efetivo.

  Taylor (1993):       i = r* + pi + 0,5 (pi - 2) + 0,5 * hiato
  Abordagem balanceada: i = r* + pi + 0,5 (pi - 2) + 1,0 * hiato      (Yellen/Fed)

pi = inflacao (core PCE, 12 meses), hiato = hiato do produto em % (GDPC1 contra GDPPOT do CBO).
r* = juro real neutro (default 0,75%, proximo da mediana de longo prazo do SEP; ajustavel).
"""

from dataclasses import dataclass
from datetime import date, timedelta

from fundo.macro import dados


@dataclass(frozen=True)
class ResultadoTaylor:
    taylor_1993: float
    balanceada: float
    fed_funds: float
    pi: float
    hiato: float
    r_neutro: float

    @property
    def folga_taylor(self) -> float:
        """Fed Funds menos juro justo (positivo = politica mais apertada que a regra)."""
        return self.fed_funds - self.taylor_1993


def regra_taylor(pi: float, hiato: float, r_neutro: float = 0.75, meta: float = 2.0) -> tuple[float, float]:
    base = r_neutro + pi + 0.5 * (pi - meta)
    return base + 0.5 * hiato, base + 1.0 * hiato


def taylor_atual(r_neutro: float = 0.75) -> ResultadoTaylor:
    ff = dados.fred("DFF", inicio=(date.today() - timedelta(days=30)).isoformat())[-1][1]
    pce = dados.fred("PCEPILFE", inicio="2023-01-01")
    pi = dados.variacao_12m(pce, 12)
    gdp = dados.fred("GDPC1", inicio="2015-01-01")
    pot = dict(dados.fred("GDPPOT", inicio="2015-01-01"))
    d, v = gdp[-1]
    # GDPPOT pode ter data posterior ao ultimo GDPC1 publicado: pega a data exata ou a mais proxima
    p = pot.get(d) or pot[min(pot, key=lambda k: abs((k - d).days))]
    hiato = (v / p - 1.0) * 100.0
    t, b = regra_taylor(pi, hiato, r_neutro)
    return ResultadoTaylor(t, b, ff, pi, hiato, r_neutro)
