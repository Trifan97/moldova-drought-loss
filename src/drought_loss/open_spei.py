"""Read the open 0.5 degree SPEI cells over Moldova, used only to calibrate the generator.

Each workbook holds one grid cell, on a sheet titled like 'SPEI_45 75_28 25 - MD006' (cell
centre 45.75 N, 28.25 E), with a DATA column ('Jan1950') and columns SPEI_1 to SPEI_48: the
layout of a CSIC single-cell export. Districts that share a cell share a workbook.
"""

import re
from pathlib import Path

import openpyxl
import pandas as pd

SHEET_TITLE = re.compile(r"SPEI_(\d+)[ .,_](\d+)_(\d+)[ .,_](\d+)")
# A standardised index cannot sit ten deviations below its mean, so anything lower is a
# missing-value code.
MISSING_BELOW = -10.0
COLUMNS = {"SPEI_1": "spei_1", "SPEI_3": "spei_3"}


def read_cell_workbook(path: Path) -> pd.DataFrame:
    """One cell as rows of lat, lon, year, month, spei_1, spei_3."""
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = next((s for s in workbook.worksheets if SHEET_TITLE.search(s.title)), None)
        if sheet is None:
            raise ValueError(f"{path.name}: no sheet titled like 'SPEI_45 75_28 25'")
        match = SHEET_TITLE.search(sheet.title)
        assert match is not None
        rows = sheet.iter_rows(values_only=True)
        header = [str(cell).strip() if cell is not None else "" for cell in next(rows)]
        wanted = ["DATA", *COLUMNS]
        missing = [name for name in wanted if name not in header]
        if missing:
            raise ValueError(f"{path.name}: missing columns {missing}")
        positions = [header.index(name) for name in wanted]
        records = [[row[i] for i in positions] for row in rows if row[positions[0]] is not None]
    finally:
        workbook.close()

    frame = pd.DataFrame(records, columns=wanted)
    stamps = frame["DATA"].map(
        lambda v: pd.to_datetime(v, format="%b%Y") if isinstance(v, str) else pd.Timestamp(v)
    )
    out = pd.DataFrame(
        {
            "lat": float(f"{match[1]}.{match[2]}"),
            "lon": float(f"{match[3]}.{match[4]}"),
            "year": stamps.dt.year,
            "month": stamps.dt.month,
        }
    )
    for source, target in COLUMNS.items():
        values = pd.to_numeric(frame[source], errors="coerce")
        out[target] = values.where(values > MISSING_BELOW)
    return out


def as_sites(cells: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The cells in the layout the hazard reads for stations: a `station` id per cell, plus a
    site table (index: that id, columns lat and lon)."""
    ids = cells["lat"].map("{:.2f}N".format) + "_" + cells["lon"].map("{:.2f}E".format)
    named = cells.assign(station=ids)
    sites = named.drop_duplicates("station").set_index("station")[["lat", "lon"]]
    return named[["station", "year", "month", "spei_3"]], sites


def read_cells(folder: Path, pattern: str = "MD0*.xlsm") -> pd.DataFrame:
    """Every cell in the folder, one row per cell and month."""
    paths = sorted(folder.glob(pattern))
    if not paths:
        raise FileNotFoundError(f"no files matching {pattern} in {folder}")
    cells = pd.concat([read_cell_workbook(path) for path in paths], ignore_index=True)
    keys = ["lat", "lon", "year", "month"]
    duplicated = cells.duplicated(keys, keep=False)
    if duplicated.any():
        # Two workbooks for one cell must agree, or one of them is not what its title says.
        spread = cells[duplicated].groupby(keys)[list(COLUMNS.values())].nunique().max().max()
        if spread > 1:
            raise ValueError("two workbooks claim the same cell but hold different values")
        cells = cells.drop_duplicates(keys)
    return cells.sort_values(keys).reset_index(drop=True)
