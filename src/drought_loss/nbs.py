"""Crop statistics from the National Bureau of Statistics of Moldova, via its PX-Web API.

Source: National Bureau of Statistics of the Republic of Moldova, statbank.statistica.md,
licensed CC BY 4.0. Both tables exclude the districts on the left bank of the Nistru and the
municipality of Bender.
"""

import json
import urllib.parse
from pathlib import Path

import numpy as np
import pandas as pd

from drought_loss import config, downloads

API = "https://statbank.statistica.md/PxWeb/api/v1/en/"

# Sown area, yield and gross harvest by district, 2007-2025, for agricultural enterprises and
# farms of 10 ha or more (households are not in it).
DISTRICT_TABLE = "40 Statistica economica/16 AGR/AGR020/AGR020600reg.px"
DISTRICT_FILENAME = "nbs_AGR020600reg.json"
DISTRICT_CROPS = {"2": "winter_wheat", "14": "sunflower", "7": "maize"}
DISTRICT_YEARS = [str(year) for year in range(2007, 2026)]
WHOLE_COUNTRY = "0"
REGIONS = ["MD011", "MD012", "MD013"]

# The same crops for the whole country, split by category of producer, 2016-2025. Used to
# scale the district figures up to every producer, households included. The crop codes differ
# from the district table's.
NATIONAL_TABLE = "40 Statistica economica/16 AGR/AGR020/AGR020060.px"
NATIONAL_FILENAME = "nbs_AGR020060.json"
NATIONAL_CROPS = {"2": "winter_wheat", "26": "sunflower", "10": "maize"}
NATIONAL_YEARS = [str(year) for year in range(2016, 2026)]
CATEGORIES = {"0": "all", "1": "enterprises", "2": "farms", "3": "households"}

# NBS district code -> geoBoundaries ADM1 name, written out rather than matched by spelling so
# that every pairing can be read and checked. geoBoundaries garbles two names (RIscani,
# SIngerei). Its Bender and Transnistria have no NBS counterpart, so they carry no exposure.
DISTRICTS = {
    "01": "Chisinau",
    "03": "Balti",
    "14": "Briceni",
    "34": "Donduseni",
    "36": "Drochia",
    "41": "Edinet",
    "43": "Falesti",
    "45": "Floresti",
    "48": "Glodeni",
    "62": "Ocnita",
    "71": "RIscani",
    "74": "SIngerei",
    "78": "Soroca",
    "10": "Anenii Noi",
    "25": "Calarasi",
    "31": "Criuleni",
    "38": "Dubasari",
    "53": "Hincesti",
    "55": "Ialoveni",
    "60": "Nisporeni",
    "64": "Orhei",
    "67": "Rezina",
    "80": "Straseni",
    "83": "Soldanesti",
    "89": "Telenesti",
    "92": "Ungheni",
    "12": "Basarabeasca",
    "17": "Cahul",
    "21": "Cantemir",
    "27": "Causeni",
    "29": "Cimislia",
    "57": "Leova",
    "85": "Stefan Voda",
    "87": "Taraclia",
    "96": "Gagauzia",
}


def query(selections: dict[str, list[str]]) -> bytes:
    """A PX-Web query naming every value explicitly, so the response stays the same over time."""
    body = {
        "query": [
            {"code": code, "selection": {"filter": "item", "values": values}}
            for code, values in selections.items()
        ],
        "response": {"format": "json"},
    }
    return json.dumps(body).encode("utf-8")


def district_query() -> bytes:
    return query(
        {
            "Raioane/Regiuni": [WHOLE_COUNTRY, *REGIONS, *DISTRICTS],
            "Culturi agricole": list(DISTRICT_CROPS),
            "Ani": DISTRICT_YEARS,
            "Indicatori": ["0", "1", "2"],
        }
    )


def national_query() -> bytes:
    return query(
        {
            "Culturi": list(NATIONAL_CROPS),
            "Ani": NATIONAL_YEARS,
            "Categorii de gospodarii": list(CATEGORIES),
            "Indicatori": ["0", "1", "2"],
        }
    )


def download_tables() -> list[Path]:
    tables = [
        (DISTRICT_TABLE, DISTRICT_FILENAME, district_query(), config.NBS_DISTRICT_SHA256),
        (NATIONAL_TABLE, NATIONAL_FILENAME, national_query(), config.NBS_NATIONAL_SHA256),
    ]
    return [
        downloads.fetch_verified(
            API + urllib.parse.quote(table), config.RAW_DIR / filename, pin, data=body
        )
        for table, filename, body, pin in tables
    ]


def parse_px_json(path: Path) -> pd.DataFrame:
    """One row per cell: a column per dimension code, plus `value`.

    NBS marks "the event did not exist" with "-", which is a true zero, and an unavailable
    figure with "..", which is missing.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    codes = [column["code"] for column in payload["columns"] if column["type"] != "c"]
    rows = [[*cell["key"], cell["values"][0]] for cell in payload["data"]]
    frame = pd.DataFrame(rows, columns=[*codes, "raw"])
    frame["value"] = pd.to_numeric(frame["raw"].replace({"-": "0", "..": np.nan}), errors="raise")
    return frame.drop(columns="raw")


def read_district_table(path: Path = config.RAW_DIR / DISTRICT_FILENAME) -> pd.DataFrame:
    """Columns: code, crop, year, area_ha, yield_t_ha, harvest_t (quintals become tonnes)."""
    cells = parse_px_json(path)
    # pivot, not pivot_table: it keeps only combinations present in the file, and it raises on a
    # duplicated cell instead of silently averaging it.
    wide = cells.pivot(
        index=["Raioane/Regiuni", "Culturi agricole", "Ani"], columns="Indicatori", values="value"
    ).reset_index()
    return pd.DataFrame(
        {
            "code": wide["Raioane/Regiuni"],
            "crop": wide["Culturi agricole"].map(DISTRICT_CROPS),
            "year": wide["Ani"].astype(int),
            "area_ha": wide["0"],
            "yield_t_ha": wide["1"] / 10,
            "harvest_t": wide["2"] / 10,
        }
    )


def read_national_table(path: Path = config.RAW_DIR / NATIONAL_FILENAME) -> pd.DataFrame:
    """Columns: crop, year, category, area_ha, yield_t_ha, production_t (thousands become units)."""
    cells = parse_px_json(path)
    wide = cells.pivot(
        index=["Culturi", "Ani", "Categorii de gospodarii"], columns="Indicatori", values="value"
    ).reset_index()
    return pd.DataFrame(
        {
            "crop": wide["Culturi"].map(NATIONAL_CROPS),
            "year": wide["Ani"].astype(int),
            "category": wide["Categorii de gospodarii"].map(CATEGORIES),
            "area_ha": wide["0"] * 1000,
            "yield_t_ha": wide["1"] / 10,
            "production_t": wide["2"] * 1000,
        }
    )
