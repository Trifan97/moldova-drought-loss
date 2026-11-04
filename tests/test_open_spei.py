"""The cell reader understands the CSIC single-cell layout, on small workbooks built here."""

from collections.abc import Sequence
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from drought_loss import open_spei


def write_cell(path: Path, title: str, rows: Sequence[tuple[object, ...]]) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = title
    sheet.append(("Year", "Month", "DATA", "SPEI_1", "SPEI_2", "SPEI_3"))
    for row in rows:
        sheet.append(row)
    workbook.save(path)


ROWS = [
    (1950, 1, "Jan1950", 0.4, None, None),
    (1950, 2, "Feb1950", -1.2, 0.1, None),
    (1950, 3, "Mar1950", -99.9, -0.5, -0.3),
]


def test_reads_coordinates_from_the_sheet_title_and_dates_from_data(tmp_path: Path) -> None:
    write_cell(tmp_path / "MD006.xlsx", "SPEI_45 75_28 25 - MD006", ROWS)
    cell = open_spei.read_cell_workbook(tmp_path / "MD006.xlsx")
    assert list(cell.columns) == ["lat", "lon", "year", "month", "spei_1", "spei_3"]
    assert (cell.lat == 45.75).all() and (cell.lon == 28.25).all()
    assert list(zip(cell.year, cell.month, strict=True)) == [(1950, 1), (1950, 2), (1950, 3)]


def test_missing_value_codes_become_nan(tmp_path: Path) -> None:
    write_cell(tmp_path / "MD006.xlsx", "SPEI_45 75_28 25 - MD006", ROWS)
    cell = open_spei.read_cell_workbook(tmp_path / "MD006.xlsx")
    assert pd.isna(cell.spei_1.iloc[2])
    assert cell.spei_3.iloc[2] == pytest.approx(-0.3)


def test_a_workbook_shared_by_districts_counts_once(tmp_path: Path) -> None:
    write_cell(tmp_path / "MD001 MD004.xlsx", "SPEI_46 75_29 25 - MD001", ROWS)
    write_cell(tmp_path / "MD009.xlsx", "SPEI_46 75_29 25 - MD009", ROWS)
    cells = open_spei.read_cells(tmp_path, pattern="*.xlsx")
    assert len(cells) == len(ROWS)


def test_two_workbooks_disagreeing_about_one_cell_are_refused(tmp_path: Path) -> None:
    write_cell(tmp_path / "a.xlsx", "SPEI_46 75_29 25 - MD001", ROWS)
    changed = [ROWS[0], (1950, 2, "Feb1950", 0.9, 0.1, None), ROWS[2]]
    write_cell(tmp_path / "b.xlsx", "SPEI_46 75_29 25 - MD009", changed)
    with pytest.raises(ValueError, match="different values"):
        open_spei.read_cells(tmp_path, pattern="*.xlsx")


def test_an_empty_folder_is_an_error_not_an_empty_table(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_spei.read_cells(tmp_path)
