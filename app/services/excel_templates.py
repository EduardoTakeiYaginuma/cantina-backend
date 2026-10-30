"""
Ajuda para os modelos (templates) de importação em Excel.

Os exemplos ficam numa aba separada "INSTRUÇÕES", que a importação não lê.
Assim, quem baixa o modelo não importa por engano a linha de exemplo.
"""
from typing import Iterable, List, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

INSTRUCTIONS_SHEET = "INSTRUÇÕES"

_HEADER_FILL = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
_HEADER_FONT = Font(color="FFFFFF", bold=True)


def add_instructions_sheet(
        wb: Workbook,
        lines: Iterable[str],
        example_headers: Sequence[str],
        example_rows: List[Sequence],
) -> None:
    ws = wb.create_sheet(title=INSTRUCTIONS_SHEET)
    ws.column_dimensions["A"].width = 30
    row = 1
    for line in lines:
        ws.cell(row=row, column=1, value=line)
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Exemplo de preenchimento (não é importado):").font = Font(bold=True)
    row += 1
    for col, header in enumerate(example_headers, 1):
        cell = ws.cell(row=row, column=col, value=header)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
    for example in example_rows:
        row += 1
        for col, value in enumerate(example, 1):
            ws.cell(row=row, column=col, value=value)


def pick_data_sheet(wb: Workbook, preferred: str):
    """Aba de dados: a com o nome esperado ou a primeira que não seja a de instruções."""
    if preferred in wb.sheetnames:
        return wb[preferred]
    for name in wb.sheetnames:
        if name != INSTRUCTIONS_SHEET:
            return wb[name]
    return wb.active
