"""Recalculo do Excel no LibreOffice (headless) e conferencia contra o DCF em Python.

O openpyxl escreve formulas mas nao calcula; o LibreOffice abre o arquivo, calcula e salva
com os valores em cache. A conferencia compara esses valores com fundo.valuation.dcf: se
divergirem, o Excel tem erro de formula e NAO pode virar alvo.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from openpyxl import load_workbook

from fundo.valuation import dcf


class SemLibreOffice(Exception):
    pass


class ErroDeConferencia(Exception):
    pass


def achar_soffice() -> str | None:
    return os.getenv("FUNDO_SOFFICE") or shutil.which("soffice") or shutil.which("libreoffice")


def recalcular(origem: str | Path, destino: str | Path | None = None, timeout: int = 240) -> Path:
    """Abre `origem` no LibreOffice, recalcula e grava em `destino` (padrao: sobrescreve)."""
    exe = achar_soffice()
    if not exe:
        raise SemLibreOffice("LibreOffice (soffice) nao encontrado; instale libreoffice-calc")
    origem = Path(origem).resolve()
    destino = Path(destino).resolve() if destino else origem
    with tempfile.TemporaryDirectory() as tmp:
        perfil = Path(tmp) / "perfil"
        saida = Path(tmp) / "saida"
        saida.mkdir()
        cmd = [exe, f"-env:UserInstallation=file://{perfil.as_posix()}", "--headless", "--norestore",
               "--calc", "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(saida), str(origem)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        gerado = saida / origem.name
        if r.returncode != 0 or not gerado.exists():
            raise RuntimeError(f"LibreOffice falhou ({r.returncode}): {r.stderr[:300] or r.stdout[:300]}")
        shutil.copyfile(gerado, destino)
    return destino


def ler_valores(xlsx: str | Path) -> "load_workbook":
    return load_workbook(xlsx, data_only=True)


def _celula(wb, endereco: str):
    aba, cel = endereco.split("!")
    return wb[aba][cel].value


def conferir(xlsx_recalculado: str | Path, celulas: dict, premissas: dict[str, dcf.Premissas],
             probabilidades: dict[str, float], tolerancia: float = 1e-6) -> dict:
    """Compara saidas-chave do Excel com o DCF em Python. Levanta ErroDeConferencia se divergir."""
    wb = ler_valores(xlsx_recalculado)
    res = {c: dcf.valuation(p) for c, p in premissas.items()}
    esperado = {
        "alvo_ponderado": dcf.alvo_ponderado(res, probabilidades),
        "retorno_esperado": dcf.alvo_ponderado(res, probabilidades) / premissas["base"].preco_atual - 1.0,
        "sensibilidade_centro": dcf.sensibilidade(premissas["base"])[(0.0, 0.03)],
    }
    diffs = []

    def cmp(nome, obtido, certo):
        if not isinstance(obtido, (int, float)):
            diffs.append(f"{nome}: valor nao numerico no Excel ({obtido!r})")
        elif abs(obtido - certo) > tolerancia * max(1.0, abs(certo)):
            diffs.append(f"{nome}: Excel={obtido:.8f} Python={certo:.8f}")

    for chave, certo in esperado.items():
        cmp(chave, _celula(wb, celulas[chave]), certo)
    for c in dcf.CENARIOS:
        cmp(f"valor_por_acao[{c}]", _celula(wb, celulas["valor_por_acao"][c]), res[c]["valor_por_acao"])
        cmp(f"wacc[{c}]", _celula(wb, celulas["wacc"][c]), res[c]["wacc"])
        cmp(f"ev[{c}]", _celula(wb, celulas["ev"][c]), res[c]["ev"])
    if _celula(wb, celulas["checagem"]) != "OK":
        diffs.append(f"checagem interna do Excel = {_celula(wb, celulas['checagem'])!r}")
    # erros de formula (#REF!, #DIV/0!...) em qualquer aba
    for ws in wb.worksheets:
        for linha in ws.iter_rows():
            for cel in linha:
                if isinstance(cel.value, str) and cel.value.startswith("#"):
                    diffs.append(f"erro de formula em {ws.title}!{cel.coordinate}: {cel.value}")
    if diffs:
        raise ErroDeConferencia("; ".join(diffs[:10]))
    return {"ok": True, "esperado": esperado}
