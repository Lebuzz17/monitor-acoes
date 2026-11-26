"""Gera o Excel auditavel de valuation (DCF FCFF) com FORMULAS reais (openpyxl).

Regras de auditoria:
  * premissas (valores digitados) em AZUL; formulas em preto; nenhum numero colado em formula;
  * toda premissa exige fonte + trecho + data, senao o builder se recusa a gerar o arquivo;
  * tres cenarios (bear/base/bull) com projecao propria e valor ponderado por probabilidade;
  * o resultado e conferido contra fundo.valuation.dcf apos o recalculo (recalc.conferir).

Abas: Capa, Premissas, Proj_Bear, Proj_Base, Proj_Bull, Valuation, Sensibilidade, Log.
"""

from dataclasses import replace
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter as L

from fundo.valuation import dcf

ESCALARES = [  # (chave, rotulo, unidade, formato)
    ("ano_base", "Ano base (ultimo realizado)", "ano", "0"),
    ("receita_base", "Receita do ano base", "R$ mi", "#,##0.0"),
    ("nwc_pct", "Capital de giro (% da variacao da receita)", "%", "0.0%"),
    ("aliquota_ir", "Aliquota efetiva de IR/CSLL", "%", "0.0%"),
    ("rf", "Taxa livre de risco", "% a.a.", "0.00%"),
    ("erp", "Premio de risco de mercado", "% a.a.", "0.00%"),
    ("beta", "Beta", "x", "0.00"),
    ("kd_pre", "Custo da divida (antes do imposto)", "% a.a.", "0.00%"),
    ("peso_divida", "Peso da divida na estrutura alvo D/(D+E)", "%", "0.0%"),
    ("g_terminal", "Crescimento na perpetuidade (g)", "% a.a.", "0.00%"),
    ("divida_liquida", "Divida liquida", "R$ mi", "#,##0.0"),
    ("acoes", "Numero de acoes", "milhoes", "#,##0.00"),
    ("preco_atual", "Preco atual da acao", "R$", "#,##0.00"),
    ("probabilidade", "Probabilidade do cenario", "%", "0.0%"),
]
VETORES = [("crescimento", "Crescimento da receita", "0.0%"),
           ("margem_ebitda", "Margem EBITDA", "0.0%"),
           ("da_pct", "D&A (% da receita)", "0.0%"),
           ("capex_pct", "Capex (% da receita)", "0.0%")]
NOMES = {"bear": "Bear", "base": "Base", "bull": "Bull"}
COL_CEN = {"bear": "C", "base": "D", "bull": "E"}      # colunas dos cenarios na aba Premissas
AZUL = Font(color="0000FF")
NEGRITO = Font(bold=True)
CINZA = PatternFill("solid", fgColor="E4E8EE")
TITULO = Font(bold=True, size=14, color="0B2A5B")


class PremissaSemFonte(Exception):
    pass


def _validar_fontes(fontes: dict, p_base: dcf.Premissas) -> None:
    exigidas = [k for k, *_ in ESCALARES] + [k for k, *_ in VETORES]
    faltam = []
    for k in exigidas:
        f = fontes.get(k) or {}
        if not (f.get("fonte") and f.get("trecho") and f.get("data")):
            faltam.append(k)
    if faltam:
        raise PremissaSemFonte("premissas sem fonte/trecho/data: " + ", ".join(faltam))


def _valor(p: dcf.Premissas, chave: str, prob: dict[str, float], cen: str):
    if chave == "probabilidade":
        return prob[cen]
    return getattr(p, chave)


def construir(destino: str | Path, empresa: str, ticker: str, premissas: dict[str, dcf.Premissas],
              probabilidades: dict[str, float], fontes: dict[str, dict], versao: int = 1,
              status: str = "rascunho", autor: str = "Modelador", moeda: str = "R$") -> dict:
    """Escreve o .xlsx e devolve {'celulas': {...}} com os enderecos das saidas-chave."""
    if set(premissas) != set(dcf.CENARIOS):
        raise ValueError("premissas precisa ter bear, base e bull")
    if abs(sum(probabilidades.values()) - 1.0) > 1e-9:
        raise ValueError("probabilidades devem somar 1")
    _validar_fontes(fontes, premissas["base"])
    n = premissas["base"].n
    if any(p.n != n for p in premissas.values()):
        raise ValueError("todos os cenarios precisam do mesmo numero de anos")

    wb = Workbook()
    capa, prem = wb.active, wb.create_sheet("Premissas")
    capa.title = "Capa"
    projs = {c: wb.create_sheet(f"Proj_{NOMES[c]}") for c in dcf.CENARIOS}
    val, sens, log = wb.create_sheet("Valuation"), wb.create_sheet("Sensibilidade"), wb.create_sheet("Log")

    # ---------------- Premissas ----------------
    prem["A1"], prem["A1"].font = f"Premissas - {empresa} ({ticker})", TITULO
    prem["A2"] = "Azul = valor digitado (premissa com fonte). Preto = formula. Cenarios sem premissa propria apontam para a Base."
    for j, h in enumerate(["Premissa", "Unidade", "Bear", "Base", "Bull", "Fonte (documento)", "Trecho citado", "Data da fonte"]):
        c = prem.cell(row=3, column=1 + j, value=h); c.font = NEGRITO; c.fill = CINZA
    linha = {}
    r = 4
    for chave, rotulo, un, fmt in ESCALARES:
        linha[chave] = r
        prem.cell(row=r, column=1, value=rotulo); prem.cell(row=r, column=2, value=un)
        vals = {c: _valor(premissas[c], chave, probabilidades, c) for c in dcf.CENARIOS}
        for c in dcf.CENARIOS:
            cel = prem[f"{COL_CEN[c]}{r}"]
            if c != "base" and vals[c] == vals["base"] and chave != "probabilidade":
                cel.value = f"=D{r}"
            else:
                cel.value = vals[c]; cel.font = AZUL
            cel.number_format = fmt
        f = fontes[chave]
        prem.cell(row=r, column=6, value=f["fonte"]); prem.cell(row=r, column=7, value=f["trecho"])
        prem.cell(row=r, column=8, value=f["data"])
        r += 1
    r += 1
    prem.cell(row=r, column=1, value="Direcionadores anuais").font = NEGRITO
    r += 1
    prem.cell(row=r, column=1, value="Direcionador").font = NEGRITO
    prem.cell(row=r, column=2, value="Cenario").font = NEGRITO
    for j in range(n):
        prem.cell(row=r, column=3 + j, value=f"Ano {j + 1}").font = NEGRITO
    for k, h in enumerate(["Fonte (documento)", "Trecho citado", "Data da fonte"]):
        prem.cell(row=r, column=3 + n + k, value=h).font = NEGRITO
    r += 1
    linha_vet = {}
    for chave, rotulo, fmt in VETORES:
        f = fontes[chave]
        for c in dcf.CENARIOS:
            linha_vet[(chave, c)] = r
            prem.cell(row=r, column=1, value=rotulo); prem.cell(row=r, column=2, value=NOMES[c])
            for j, v in enumerate(getattr(premissas[c], chave)):
                cel = prem.cell(row=r, column=3 + j, value=v); cel.font = AZUL; cel.number_format = fmt
            prem.cell(row=r, column=3 + n, value=f["fonte"]); prem.cell(row=r, column=4 + n, value=f["trecho"])
            prem.cell(row=r, column=5 + n, value=f["data"])
            r += 1
    prem.column_dimensions["A"].width = 46
    for col in "BCDE":
        prem.column_dimensions[col].width = 13
    prem.freeze_panes = "C4"

    def esc(chave, cen):  # referencia a um escalar da aba Premissas
        return f"Premissas!${COL_CEN[cen]}${linha[chave]}"

    # ---------------- Valuation (colunas B,C,D = bear, base, bull) ----------------
    colv = {"bear": "B", "base": "C", "bull": "D"}
    val["A1"], val["A1"].font = f"Valuation - {empresa} ({ticker})", TITULO
    for c in dcf.CENARIOS:
        x = val[f"{colv[c]}3"]; x.value = NOMES[c]; x.font = NEGRITO; x.fill = CINZA
    val["A3"] = "Item"; val["A3"].font = NEGRITO; val["A3"].fill = CINZA
    rot_val = {4: "Custo do capital proprio (Ke = rf + beta x ERP)", 5: "Custo da divida liquido de IR (Kd)",
               6: "WACC", 7: "g terminal", 8: "Soma do VP dos FCFF", 9: "FCFF terminal (FCFF_N x (1+g))",
               10: "Valor terminal (Gordon)", 11: "VP do valor terminal", 12: "Valor da firma (EV)",
               13: "Divida liquida", 14: "Valor do equity", 15: "Numero de acoes (mi)",
               16: "Valor por acao", 17: "Preco atual", 18: "Upside vs preco atual",
               19: "Peso do valor terminal no EV", 20: "Probabilidade"}
    for rr, t in rot_val.items():
        val.cell(row=rr, column=1, value=t)
    ult = L(2 + n)  # ultima coluna de ano nas abas Proj (B = ano base, C.. = anos)
    for c in dcf.CENARIOS:
        v, pj = colv[c], f"Proj_{NOMES[c]}"
        f = {4: f"={esc('rf', c)}+{esc('beta', c)}*{esc('erp', c)}",
             5: f"={esc('kd_pre', c)}*(1-{esc('aliquota_ir', c)})",
             6: f"=(1-{esc('peso_divida', c)})*{v}4+{esc('peso_divida', c)}*{v}5",
             7: f"={esc('g_terminal', c)}",
             8: f"=SUM({pj}!C19:{ult}19)",
             9: f"={pj}!{ult}17*(1+{v}7)",
             10: f"={v}9/({v}6-{v}7)",
             11: f"={v}10/(1+{v}6)^{n}",
             12: f"={v}8+{v}11",
             13: f"={esc('divida_liquida', c)}",
             14: f"={v}12-{v}13",
             15: f"={esc('acoes', c)}",
             16: f"={v}14/{v}15",
             17: f"={esc('preco_atual', c)}",
             18: f"={v}16/{v}17-1",
             19: f"={v}11/{v}12",
             20: f"={esc('probabilidade', c)}"}
        fm = {4: "0.00%", 5: "0.00%", 6: "0.00%", 7: "0.00%", 18: "0.0%", 19: "0.0%", 20: "0.0%",
              16: "#,##0.00", 17: "#,##0.00", 15: "#,##0.00"}
        for rr, formula in f.items():
            cel = val[f"{v}{rr}"]; cel.value = formula; cel.number_format = fm.get(rr, "#,##0.0")
    val["A22"], val["A22"].font = "Preco-alvo ponderado por probabilidade", NEGRITO
    val["B22"] = "=SUMPRODUCT(B16:D16,B20:D20)"; val["B22"].number_format = "#,##0.00"
    val["A23"] = "Retorno esperado (alvo ponderado / preco atual - 1)"
    val["B23"] = "=B22/C17-1"; val["B23"].number_format = "0.0%"
    val["A24"] = "Checagem: WACC > g em todos os cenarios e probabilidades somam 100%"
    val["B24"] = '=IF(AND(B6>B7,C6>C7,D6>D7,ABS(SUM(B20:D20)-1)<0.000001),"OK","ERRO")'
    val.column_dimensions["A"].width = 60
    for col in "BCD":
        val.column_dimensions[col].width = 16

    # ---------------- Projecoes ----------------
    rot_proj = {3: "Ano projetado (t)", 4: "Ano calendario", 5: "Crescimento da receita", 6: "Receita",
                7: "Margem EBITDA", 8: "EBITDA", 9: "D&A (% da receita)", 10: "D&A", 11: "EBIT",
                12: "IR/CSLL sobre EBIT", 13: "NOPAT", 14: "Capex (% da receita)", 15: "Capex",
                16: "Variacao do capital de giro", 17: "FCFF", 18: "Fator de desconto", 19: "VP do FCFF"}
    for c in dcf.CENARIOS:
        ws = projs[c]
        ws["A1"], ws["A1"].font = f"Projecao {NOMES[c]} - {empresa} ({ticker})  [{moeda} milhoes]", TITULO
        for rr, t in rot_proj.items():
            ws.cell(row=rr, column=1, value=t)
        ws["B3"] = 0; ws["B4"] = f"={esc('ano_base', c)}"; ws["B6"] = f"={esc('receita_base', c)}"
        ws["B6"].number_format = "#,##0.0"
        for j in range(n):
            col, ant = L(3 + j), L(2 + j)
            def vet(chave):
                return f"=Premissas!{L(3 + j)}${linha_vet[(chave, c)]}"
            ws[f"{col}3"] = f"={ant}3+1"
            ws[f"{col}4"] = f"={ant}4+1"
            ws[f"{col}5"] = vet("crescimento")
            ws[f"{col}6"] = f"={ant}6*(1+{col}5)"
            ws[f"{col}7"] = vet("margem_ebitda")
            ws[f"{col}8"] = f"={col}6*{col}7"
            ws[f"{col}9"] = vet("da_pct")
            ws[f"{col}10"] = f"={col}6*{col}9"
            ws[f"{col}11"] = f"={col}8-{col}10"
            ws[f"{col}12"] = f"={col}11*{esc('aliquota_ir', c)}"
            ws[f"{col}13"] = f"={col}11-{col}12"
            ws[f"{col}14"] = vet("capex_pct")
            ws[f"{col}15"] = f"={col}6*{col}14"
            ws[f"{col}16"] = f"={esc('nwc_pct', c)}*({col}6-{ant}6)"
            ws[f"{col}17"] = f"={col}13+{col}10-{col}15-{col}16"
            ws[f"{col}18"] = f"=1/(1+Valuation!${colv[c]}$6)^{col}3"
            ws[f"{col}19"] = f"={col}17*{col}18"
            for rr in (5, 7, 9, 14):
                ws[f"{col}{rr}"].number_format = "0.0%"
            for rr in (6, 8, 10, 11, 12, 13, 15, 16, 17, 19):
                ws[f"{col}{rr}"].number_format = "#,##0.0"
            ws[f"{col}18"].number_format = "0.0000"
        ws.column_dimensions["A"].width = 34
        ws.freeze_panes = "B5"

    # ---------------- Sensibilidade (base) ----------------
    sens["A1"], sens["A1"].font = "Sensibilidade do valor por acao (cenario Base): WACC x g", TITULO
    gs = [0.02, 0.03, 0.04, 0.05]
    deltas = [-0.02, -0.01, 0.0, 0.01, 0.02]
    sens["A3"] = "WACC \\ g"; sens["A3"].font = NEGRITO
    for k, g in enumerate(gs):
        c = sens.cell(row=3, column=2 + k, value=g); c.font = AZUL; c.number_format = "0.0%"
    pb = "Proj_Base"
    for i, d in enumerate(deltas):
        rr = 4 + i
        sens.cell(row=rr, column=1, value=f"=Valuation!$C$6+({d})").number_format = "0.00%"
        for k in range(len(gs)):
            col = L(2 + k)
            w, g = f"$A{rr}", f"{col}$3"
            sens[f"{col}{rr}"] = (
                f'=IF({w}<={g},"n/a",(SUMPRODUCT({pb}!$C$17:${ult}$17/(1+{w})^{pb}!$C$3:${ult}$3)'
                f"+{pb}!${ult}$17*(1+{g})/({w}-{g})/(1+{w})^{n}-Valuation!$C$13)/Valuation!$C$15)")
            sens[f"{col}{rr}"].number_format = "#,##0.00"
    sens["A10"] = "Os deltas de WACC (-2pp a +2pp) sao parte do desenho da grade; g em azul pode ser alterado."
    sens.column_dimensions["A"].width = 16

    # ---------------- Capa e Log ----------------
    capa["A1"], capa["A1"].font = f"{empresa} ({ticker}) - Modelo de valuation (DCF)", Font(bold=True, size=16, color="0B2A5B")
    capa["A3"], capa["B3"] = "Versao", versao
    capa["A4"], capa["B4"] = "Status", status
    capa["A5"], capa["B5"] = "Data de geracao", date.today().isoformat()
    capa["A6"], capa["B6"] = "Moeda / unidade", f"{moeda} milhoes (exceto por acao)"
    capa["A8"], capa["B8"] = "Preco-alvo ponderado", "=Valuation!B22"
    capa["A9"], capa["B9"] = "Preco atual", "=Valuation!C17"
    capa["A10"], capa["B10"] = "Retorno esperado", "=Valuation!B23"
    # tres celulas numericas (TEXT() com "0.00" quebra no Excel em portugues)
    capa["A11"] = "Alvo Bear | Base | Bull"
    for col, ref in (("B", "B16"), ("C", "C16"), ("D", "D16")):
        capa[f"{col}11"] = f"=Valuation!{ref}"; capa[f"{col}11"].number_format = "#,##0.00"
    capa["A12"], capa["B12"] = "Checagem interna", "=Valuation!B24"
    capa["B8"].number_format = "#,##0.00"; capa["B9"].number_format = "#,##0.00"; capa["B10"].number_format = "0.0%"
    capa["A14"] = ("Modelo gerado por codigo. Premissas em azul na aba Premissas, cada uma com fonte, trecho e data. "
                   "Nao e recomendacao de investimento; so vira alvo apos aprovacao do dono.")
    capa["A14"].alignment = Alignment(wrap_text=True)
    capa.column_dimensions["A"].width = 28; capa.column_dimensions["B"].width = 40
    for rr in range(3, 13):
        capa[f"A{rr}"].font = NEGRITO
    for j, h in enumerate(["Data", "Versao", "Autor", "Mudanca"]):
        log.cell(row=1, column=1 + j, value=h).font = NEGRITO
    for j, v in enumerate([date.today().isoformat(), versao, autor, "Geracao inicial do modelo"]):
        log.cell(row=2, column=1 + j, value=v)
    log.column_dimensions["D"].width = 60

    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    celulas = {
        "valor_por_acao": {c: f"Valuation!{colv[c]}16" for c in dcf.CENARIOS},
        "wacc": {c: f"Valuation!{colv[c]}6" for c in dcf.CENARIOS},
        "ev": {c: f"Valuation!{colv[c]}12" for c in dcf.CENARIOS},
        "alvo_ponderado": "Valuation!B22",
        "retorno_esperado": "Valuation!B23",
        "checagem": "Valuation!B24",
        "sensibilidade_centro": "Sensibilidade!C6",   # WACC base, g = 3%
    }
    return {"celulas": celulas, "n_anos": n}
