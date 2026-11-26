"""Carregador dos dados abertos da CVM (DFP anual e ITR trimestral), sem pandas (baixo uso de RAM).

Fonte: https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{DFP|ITR}/DADOS/
Cada ZIP traz CSVs (latin-1, separador ';') por demonstracao: DRE, BPA, BPP, DFC_MI, ...
Valores vem em `ESCALA_MOEDA` (UNIDADE ou MIL); este modulo devolve em R$ MILHOES.
"""

import csv
import io
import time
import unicodedata
import zipfile
from pathlib import Path

import requests

from fundo import config

BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo}/DADOS/{prefixo}_cia_aberta_{ano}.zip"
CACHE = Path(config.DATA_DIR) / "cvm"
TTL = 24 * 3600


class CvmIndisponivel(Exception):
    pass


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).upper().strip()


def baixar(tipo: str, ano: int, forcar: bool = False) -> Path:
    tipo = tipo.upper()
    if tipo not in ("DFP", "ITR"):
        raise ValueError("tipo deve ser DFP ou ITR")
    CACHE.mkdir(parents=True, exist_ok=True)
    destino = CACHE / f"{tipo.lower()}_{ano}.zip"
    if destino.exists() and not forcar and time.time() - destino.stat().st_mtime < TTL:
        return destino
    url = BASE.format(tipo=tipo, prefixo=tipo.lower(), ano=ano)
    r = requests.get(url, timeout=180, headers={"User-Agent": "fundo-pessoal/1.0"})
    if r.status_code != 200:
        raise CvmIndisponivel(f"{url}: HTTP {r.status_code}")
    destino.write_bytes(r.content)
    return destino


def _linhas(zip_path: Path, tipo: str, ano: int, demonstracao: str, consolidado: bool):
    nome = f"{tipo.lower()}_cia_aberta_{demonstracao}_{'con' if consolidado else 'ind'}_{ano}.csv"
    with zipfile.ZipFile(zip_path) as z:
        if nome not in z.namelist():
            raise CvmIndisponivel(f"{nome} nao existe em {zip_path.name}")
        with z.open(nome) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding="latin-1", newline=""), delimiter=";")


def buscar_empresa(trecho_nome: str, ano: int, tipo: str = "DFP") -> list[dict]:
    """Empresas cujo nome contem `trecho_nome` (sem acentos/caixa): [{cd_cvm, cnpj, nome}]."""
    alvo = _norm(trecho_nome)
    achadas: dict[str, dict] = {}
    for r in _linhas(baixar(tipo, ano), tipo, ano, "DRE", True):
        if alvo in _norm(r["DENOM_CIA"]):
            achadas[r["CD_CVM"]] = {"cd_cvm": r["CD_CVM"], "cnpj": r["CNPJ_CIA"], "nome": r["DENOM_CIA"]}
    return list(achadas.values())


def contas(cd_cvm: str, ano: int, demonstracao: str, codigos: list[str], tipo: str = "DFP",
           consolidado: bool = True) -> dict:
    """Valores das contas pedidas, em R$ milhoes.

    Retorna {codigo: {'ultimo': v, 'penultimo': v, 'descricao': str, 'data': 'AAAA-MM-DD'}}.
    Usa a VERSAO mais recente do documento. Conta ausente simplesmente nao aparece no retorno.
    """
    cd = str(cd_cvm).zfill(6)
    melhor_versao = -1
    linhas = []
    for r in _linhas(baixar(tipo, ano), tipo, ano, demonstracao, consolidado):
        if r["CD_CVM"] != cd or r["CD_CONTA"] not in codigos:
            continue
        v = int(r["VERSAO"])
        if v > melhor_versao:
            melhor_versao, linhas = v, []
        if v == melhor_versao:
            linhas.append(r)
    out: dict = {}
    for r in linhas:
        escala = 1000.0 if r["ESCALA_MOEDA"].upper() == "MIL" else 1.0
        valor = float(r["VL_CONTA"]) * escala / 1e6
        ordem = _norm(r["ORDEM_EXERC"])
        chave = "penultimo" if ordem.startswith("PEN") else "ultimo"
        d = out.setdefault(r["CD_CONTA"], {"descricao": r["DS_CONTA"], "data": r["DT_REFER"]})
        d[chave] = valor
        if chave == "ultimo":
            d["data"] = r["DT_FIM_EXERC"]
    return out


# contas padrao (plano de contas da CVM para empresas nao financeiras)
RECEITA, EBIT, LUCRO_LIQUIDO = "3.01", "3.05", "3.11"
CAIXA, APLICACOES = "1.01.01", "1.01.02"
EMPRESTIMOS_CP, EMPRESTIMOS_LP = "2.01.04", "2.02.01"


def historico_dre(cd_cvm: str, ano_final: int, anos: int = 5) -> dict[int, dict]:
    """Receita, EBIT e lucro liquido por ano (R$ mi), a partir das DFPs. {ano: {...}}."""
    out: dict[int, dict] = {}
    for a in range(ano_final, ano_final - max(1, anos // 2 + 1), -1):
        try:
            c = contas(cd_cvm, a, "DRE", [RECEITA, EBIT, LUCRO_LIQUIDO])
        except CvmIndisponivel:
            continue
        for k, nome in ((RECEITA, "receita"), (EBIT, "ebit"), (LUCRO_LIQUIDO, "lucro_liquido")):
            if k in c:
                if "ultimo" in c[k]:
                    out.setdefault(a, {})[nome] = c[k]["ultimo"]
                if "penultimo" in c[k]:
                    out.setdefault(a - 1, {}).setdefault(nome, c[k]["penultimo"])
    return dict(sorted(out.items()))


def divida_liquida(cd_cvm: str, ano: int) -> dict:
    """Divida bruta (emprestimos CP+LP) menos caixa e aplicacoes, em R$ mi. Confira as notas da empresa:
    arrendamentos e outras dividas podem ficar de fora do plano de contas padrao."""
    bpp = contas(cd_cvm, ano, "BPP", [EMPRESTIMOS_CP, EMPRESTIMOS_LP])
    bpa = contas(cd_cvm, ano, "BPA", [CAIXA, APLICACOES])
    g = lambda d, k: d.get(k, {}).get("ultimo", 0.0)
    bruta = g(bpp, EMPRESTIMOS_CP) + g(bpp, EMPRESTIMOS_LP)
    caixa = g(bpa, CAIXA) + g(bpa, APLICACOES)
    return {"divida_bruta": bruta, "caixa": caixa, "divida_liquida": bruta - caixa}
