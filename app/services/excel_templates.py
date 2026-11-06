"""
Modelos (templates) de importação em Excel e leitura das planilhas.

- `build_data_sheet`: aba de dados com cabeçalho colorido, "*" nos obrigatórios, nota em cada
  cabeçalho, linha do cabeçalho fixa, filtro, formatos (R$, inteiro) e validações.
- `add_instructions_sheet`: aba "INSTRUÇÕES" com o passo a passo, a tabela das colunas e exemplos.
  A importação não lê essa aba, então o exemplo nunca é importado por engano.
- `header_columns`: acha as colunas pelo nome do cabeçalho (aceita o nome novo e o antigo).
"""
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

INSTRUCTIONS_SHEET = "INSTRUÇÕES"
LISTS_SHEET = "_listas"

# Cores do sistema (verde)
GREEN = "15803D"
GREEN_DARK = "14532D"
GREEN_LIGHT = "F0FDF4"
GREEN_SOFT = "DCFCE7"
GRAY_TEXT = "6B7280"
BORDER_GRAY = "D1D5DB"

_HEADER_FILL = PatternFill(start_color=GREEN, end_color=GREEN, fill_type="solid")
_HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
_ZEBRA_FILL = PatternFill(start_color=GREEN_LIGHT, end_color=GREEN_LIGHT, fill_type="solid")
_SOFT_FILL = PatternFill(start_color=GREEN_SOFT, end_color=GREEN_SOFT, fill_type="solid")
_THIN = Side(style="thin", color=BORDER_GRAY)
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

MONEY_FORMAT = '"R$" #,##0.00'
INT_FORMAT = "0"

# Quantas linhas já vêm formatadas para preencher
FORMATTED_ROWS = 300


@dataclass
class Col:
    header: str
    width: int = 18
    required: bool = False
    note: str = ""                  # aparece ao passar o mouse no cabeçalho e na aba de instruções
    example: str = ""               # exemplo curto para a tabela de instruções
    kind: str = "text"              # text | money | int
    options: Optional[List[str]] = None   # lista para escolher (aceita outro valor com aviso)
    options_strict: bool = False

    @property
    def label(self) -> str:
        return f"{self.header} *" if self.required else self.header


@dataclass
class ExampleTable:
    title: str
    cols: Sequence[Col]
    rows: List[Sequence]
    note: str = ""


def _style_header(cell):
    cell.fill = _HEADER_FILL
    cell.font = _HEADER_FONT
    cell.border = _BORDER
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _lists_sheet(wb: Workbook):
    if LISTS_SHEET in wb.sheetnames:
        return wb[LISTS_SHEET]
    ws = wb.create_sheet(LISTS_SHEET)
    ws.sheet_state = "hidden"
    return ws


def build_data_sheet(wb: Workbook, title: str, cols: Sequence[Col], tab_color: str = GREEN):
    """Aba de dados pronta para preencher (cabeçalho na linha 1, dados a partir da linha 2)."""
    ws = wb.create_sheet(title=title)
    ws.sheet_properties.tabColor = tab_color
    last_row = FORMATTED_ROWS + 1

    for i, col in enumerate(cols, 1):
        letter = get_column_letter(i)
        cell = ws.cell(row=1, column=i, value=col.label)
        _style_header(cell)
        if col.note:
            comment = Comment(col.note, "Cantina")
            comment.width, comment.height = 260, 90
            cell.comment = comment
        ws.column_dimensions[letter].width = col.width

        fmt = MONEY_FORMAT if col.kind == "money" else INT_FORMAT if col.kind == "int" else None
        for r in range(2, last_row + 1):
            c = ws.cell(row=r, column=i)
            c.border = _BORDER
            if r % 2 == 1:
                c.fill = _ZEBRA_FILL
            if fmt:
                c.number_format = fmt

        rng = f"{letter}2:{letter}{last_row}"
        if col.kind in ("money", "int"):
            dv = DataValidation(
                type="decimal" if col.kind == "money" else "whole", operator="greaterThanOrEqual",
                formula1="0", allow_blank=True, showErrorMessage=True, errorStyle="stop",
                errorTitle=col.header,
                error="Use um número (sem letras). Ex.: 5 ou 5,50" if col.kind == "money"
                else "Use um número inteiro, sem casas decimais. Ex.: 10",
            )
            dv.add(rng)
            ws.add_data_validation(dv)
        if col.options:
            lists = _lists_sheet(wb)
            list_col = lists.max_column + 1 if lists.max_row > 1 or lists["A1"].value else 1
            for r, opt in enumerate(col.options, 1):
                lists.cell(row=r, column=list_col, value=opt)
            ll = get_column_letter(list_col)
            dv = DataValidation(
                type="list", formula1=f"='{LISTS_SHEET}'!${ll}$1:${ll}${len(col.options)}",
                allow_blank=True, showErrorMessage=True,
                errorStyle="stop" if col.options_strict else "warning",
                errorTitle=col.header, error="Esse valor não está na lista. Quer usar mesmo assim?",
            )
            dv.add(rng)
            ws.add_data_validation(dv)

    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{last_row}"
    return ws


def add_instructions_sheet(
        wb: Workbook,
        title: str,
        steps: Iterable[str],
        cols: Sequence[Col],
        examples: Sequence[ExampleTable] = (),
        tips: Iterable[str] = (),
) -> None:
    ws = wb.create_sheet(title=INSTRUCTIONS_SHEET)
    ws.sheet_properties.tabColor = "F59E0B"
    ws.sheet_view.showGridLines = False
    for letter, width in zip("ABCDEFG", [24, 13, 58, 26, 18, 18, 18]):
        ws.column_dimensions[letter].width = width

    ws["A1"] = title
    ws["A1"].font = Font(size=18, bold=True, color=GREEN_DARK)
    ws["A2"] = "Leia antes de preencher. Esta aba não é importada."
    ws["A2"].font = Font(italic=True, color=GRAY_TEXT)
    row = 4

    def section(text):
        nonlocal row
        ws.cell(row=row, column=1, value=text).font = Font(size=13, bold=True, color=GREEN)
        row += 1

    section("Como preencher")
    for i, step in enumerate(steps, 1):
        ws.cell(row=row, column=1, value=f"{i}.").alignment = Alignment(horizontal="right", vertical="top")
        cell = ws.cell(row=row, column=2, value=step)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=5)
        ws.row_dimensions[row].height = 30 if len(step) > 95 else 18
        row += 1
    row += 1

    section("Colunas")
    for i, h in enumerate(["Coluna", "Obrigatória", "O que colocar", "Exemplo"], 1):
        _style_header(ws.cell(row=row, column=i, value=h))
    row += 1
    for n, col in enumerate(cols):
        values = [col.header, "Sim" if col.required else "Não", col.note, col.example]
        for i, v in enumerate(values, 1):
            cell = ws.cell(row=row, column=i, value=v)
            cell.border = _BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if n % 2:
                cell.fill = _ZEBRA_FILL
        ws.cell(row=row, column=1).font = Font(bold=True)
        if col.required:
            ws.cell(row=row, column=2).font = Font(bold=True, color=GREEN)
        ws.row_dimensions[row].height = max(18, 15 * (len(col.note) // 60 + 1))
        row += 1
    row += 1

    for ex in examples:
        section(ex.title)
        if ex.note:
            ws.cell(row=row, column=1, value=ex.note).font = Font(italic=True, color=GRAY_TEXT)
            row += 1
        for i, col in enumerate(ex.cols, 1):
            _style_header(ws.cell(row=row, column=i, value=col.label))
        row += 1
        for values in ex.rows:
            for i, (col, v) in enumerate(zip(ex.cols, values), 1):
                cell = ws.cell(row=row, column=i, value=v)
                cell.border = _BORDER
                cell.fill = _SOFT_FILL
                if col.kind == "money" and isinstance(v, (int, float)):
                    cell.number_format = MONEY_FORMAT
            row += 1
        row += 1

    tips = list(tips)
    if tips:
        section("Dicas")
        for tip in tips:
            cell = ws.cell(row=row, column=1, value=f"•  {tip}")
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[row].height = 30 if len(tip) > 110 else 18
            row += 1


def new_workbook() -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)
    return wb


def finish_workbook(wb: Workbook, first_sheet: str):
    """Abre o arquivo na primeira aba de dados e manda a aba de listas para o fim."""
    if LISTS_SHEET in wb.sheetnames:
        wb.move_sheet(LISTS_SHEET, offset=len(wb.sheetnames))
    wb.active = wb.sheetnames.index(first_sheet)


# ============================================
# Leitura
# ============================================

def pick_data_sheet(wb: Workbook, preferred: str):
    """Aba de dados: a com o nome esperado ou a primeira que não seja de instruções/listas."""
    if preferred in wb.sheetnames:
        return wb[preferred]
    for name in wb.sheetnames:
        if name not in (INSTRUCTIONS_SHEET, LISTS_SHEET):
            return wb[name]
    return wb.active


def normalize_header(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"\(.*?\)", " ", text)               # "Preço (R$)" -> "preco"
    return " ".join(re.split(r"[^a-z0-9]+", text)).strip()


def header_columns(ws, aliases: Dict[str, Sequence[str]]) -> Dict[str, int]:
    """{campo: índice da coluna} a partir do cabeçalho (linha 1). Só os campos encontrados."""
    found = {}
    first = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
    normalized = [normalize_header(v) for v in first]
    for field_name, names in aliases.items():
        wanted = {normalize_header(n) for n in names}
        for idx, h in enumerate(normalized):
            if h in wanted and idx not in found.values():
                found[field_name] = idx
                break
    return found


def parse_number(value, cast=float):
    """Aceita 5, 5.5, "5,50" e "R$ 5,50". Vazio = None."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.replace("R$", "").replace(" ", "").strip()
        if value == "":
            return None
        if "," in value:
            value = value.replace(".", "").replace(",", ".")
    number = float(value)
    if cast is int and number != int(number):
        raise ValueError("não é inteiro")
    return cast(number)
