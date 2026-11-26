"""Carregadores de dados macro (todos gratuitos, sem chave).

  * BCB SGS    - series historicas (Selic, IPCA, cambio, IBC-Br...)
  * BCB Focus  - expectativas de mercado (API Olinda)
  * FRED       - series dos EUA via CSV publico (fredgraph.csv), sem chave

Regra do projeto: numeros macro vem SO daqui (codigo). O LLM nunca preenche numero:
se uma fonte falhar, a funcao levanta DadosIndisponiveis e quem chama mostra "n/d".
"""

import csv
import io
import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import requests

from fundo import config

logger = logging.getLogger(__name__)

SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
FOCUS = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# codigos SGS usados
SGS_SELIC_META = 432
SGS_IPCA_MENSAL = 433
SGS_IPCA_12M = 13522
SGS_CAMBIO_VENDA = 1        # dolar comercial, venda (PTAX)
SGS_IBC_BR = 24364          # IBC-Br dessazonalizado (24363 e a serie bruta, ruidosa)
SGS_SELIC_OVER_DIARIA = 11

CACHE_DIR = Path(config.DATA_DIR) / "cache"
TTL_PADRAO = 6 * 3600


class DadosIndisponiveis(Exception):
    pass


def _cache_get(chave: str, ttl: int):
    p = CACHE_DIR / (chave.replace("/", "_")[:150] + ".json")
    if p.exists() and time.time() - p.stat().st_mtime < ttl:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _cache_put(chave: str, dados) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / (chave.replace("/", "_")[:150] + ".json")).write_text(
            json.dumps(dados), encoding="utf-8")
    except OSError as exc:  # cache e opcional
        logger.warning("cache nao gravado: %s", exc)


def _http(url: str, params: dict | None = None, tentativas: int = 3) -> requests.Response:
    ultimo = None
    for i in range(tentativas):
        try:
            r = requests.get(url, params=params, timeout=40,
                             headers={"User-Agent": "fundo-pessoal/1.0"})
            if r.status_code == 200:
                return r
            ultimo = f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            ultimo = str(exc)
        time.sleep(2 * (i + 1))
    raise DadosIndisponiveis(f"{url}: {ultimo}")


def sgs(codigo: int, inicio: date | None = None, ultimos: int | None = None,
        ttl: int = TTL_PADRAO) -> list[tuple[date, float]]:
    """Serie do SGS como [(data, valor)] em ordem crescente."""
    if ultimos is not None and ultimos > 20:  # limite atual da API do SGS em /ultimos/N
        raise ValueError("SGS aceita no maximo 20 em 'ultimos'; use inicio=")
    chave = f"sgs_{codigo}_{inicio}_{ultimos}"
    bruto = _cache_get(chave, ttl)
    if bruto is None:
        url = SGS.format(codigo=codigo)
        if ultimos:
            url += f"/ultimos/{int(ultimos)}"
            params = {"formato": "json"}
        else:
            params = {"formato": "json"}
            if inicio:
                params["dataInicial"] = inicio.strftime("%d/%m/%Y")
        bruto = _http(url, params).json()
        _cache_put(chave, bruto)
    out = []
    hoje = date.today()
    for x in bruto:
        try:
            d = datetime.strptime(x["data"], "%d/%m/%Y").date()
            if d > hoje:  # algumas series (ex.: meta Selic) trazem datas futuras agendadas
                continue
            out.append((d, float(x["valor"])))
        except (KeyError, ValueError):
            continue
    if not out:
        raise DadosIndisponiveis(f"SGS {codigo} vazia")
    return sorted(out)


def _olinda(entidade: str, filtro: str, ordenar: str | None = None, top: int = 500,
            select: str | None = None, ttl: int = TTL_PADRAO) -> list[dict]:
    chave = f"focus_{entidade}_{filtro}_{ordenar}_{top}_{select}"
    v = _cache_get(chave, ttl)
    if v is None:
        # Olinda exige %20 (nao '+') nos espacos: monta a query na mao.
        partes = [f"$filter={quote(filtro)}", f"$top={top}", "$format=json"]
        if ordenar:
            partes.append(f"$orderby={quote(ordenar)}")
        if select:
            partes.append(f"$select={quote(select)}")
        v = _http(f"{FOCUS}/{entidade}?" + "&".join(partes)).json()["value"]
        _cache_put(chave, v)
    return v


def focus_ultima_data(indicador: str = "IPCA") -> str:
    r = _olinda("ExpectativasMercadoAnuais", f"Indicador eq '{indicador}' and baseCalculo eq 0",
                ordenar="Data desc", top=1)
    if not r:
        raise DadosIndisponiveis("Focus sem dados")
    return r[0]["Data"]


def focus_anual(indicador: str, ano: int, data: str | None = None) -> dict:
    """Mediana/minimo/maximo do Focus para o ano-calendario (baseCalculo=0: ultimos 30 dias)."""
    data = data or focus_ultima_data(indicador)
    r = _olinda("ExpectativasMercadoAnuais",
                f"Indicador eq '{indicador}' and Data eq '{data}' and DataReferencia eq '{ano}' and baseCalculo eq 0",
                top=1)
    if not r:
        raise DadosIndisponiveis(f"Focus {indicador} {ano} em {data} sem dados")
    x = r[0]
    return {"data": x["Data"], "mediana": x["Mediana"], "media": x["Media"],
            "minimo": x["Minimo"], "maximo": x["Maximo"], "n": x.get("numeroRespondentes")}


def focus_selic_fim_de_ano(ano: int, data: str | None = None) -> float:
    """Mediana Focus da Selic ao fim do ano (ExpectativasMercadoAnuais, indicador 'Selic')."""
    return focus_anual("Selic", ano, data)["mediana"]


def fred(serie: str, inicio: str | None = None, ttl: int = TTL_PADRAO) -> list[tuple[date, float]]:
    """Serie do FRED via CSV publico. Pontos '.' (ausentes) sao descartados."""
    chave = f"fred_{serie}_{inicio}"
    texto = _cache_get(chave, ttl)
    if texto is None:
        params = {"id": serie}
        if inicio:
            params["cosd"] = inicio
        texto = _http(FRED, params).text
        _cache_put(chave, texto)
    out = []
    for linha in csv.DictReader(io.StringIO(texto)):
        vals = list(linha.values())
        try:
            out.append((date.fromisoformat(vals[0]), float(vals[1])))
        except (ValueError, TypeError, IndexError):
            continue
    if not out:
        raise DadosIndisponiveis(f"FRED {serie} vazia")
    return out


def variacao_12m(serie: list[tuple[date, float]], passo: int = 12) -> float:
    """Variacao % do ultimo ponto contra `passo` pontos antes (serie mensal: 12 = 12 meses)."""
    if len(serie) <= passo:
        raise DadosIndisponiveis("serie curta demais")
    return (serie[-1][1] / serie[-1 - passo][1] - 1.0) * 100.0
