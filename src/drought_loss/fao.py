"""Producer prices for Moldova from FAOSTAT (FAO, CC BY 4.0).

FAOSTAT only offers the global bulk file (11 MB), and it changes whenever any country's data
is updated. So the pipeline keeps, and pins, just Moldova's annual prices for the three crops;
an update elsewhere in the world does not break the pin, but a revision to Moldova's does.
"""

import zipfile
from pathlib import Path

import pandas as pd

from drought_loss import config, downloads

BULK_URL = "https://bulks-faostat.fao.org/production/Prices_E_All_Data_(Normalized).zip"
FILENAME = "faostat_producer_prices_moldova.csv"
AREA = "Republic of Moldova"
ELEMENT = "Producer Price (USD/tonne)"
# Moldova's wheat is almost all winter wheat, so the wheat price stands for it.
ITEMS = {"Wheat": "winter_wheat", "Sunflower seed": "sunflower", "Maize (corn)": "maize"}
COLUMNS = ["Area", "Item", "Element", "Year", "Months", "Unit", "Value", "Flag"]


def extract_moldova(zip_path: Path, dest: Path) -> Path:
    """Moldova's annual producer prices for the three crops, as a small sorted CSV."""
    with zipfile.ZipFile(zip_path) as archive:
        name = next(n for n in archive.namelist() if n.endswith("(Normalized).csv"))
        with archive.open(name) as handle:
            # Latin-1 decodes any byte, so other countries' names can never stop the read;
            # Moldova's rows are plain ASCII either way.
            prices = pd.read_csv(handle, usecols=COLUMNS, encoding="latin-1", dtype=str)
    keep = (
        (prices["Area"] == AREA)
        & prices["Item"].isin(list(ITEMS))
        & (prices["Element"] == ELEMENT)
        & (prices["Months"] == "Annual value")
    )
    moldova = prices[keep].sort_values(["Item", "Year"])
    moldova.to_csv(dest, index=False, lineterminator="\n")
    return dest


def download_prices(
    dest: Path = config.RAW_DIR / FILENAME, expected_sha256: str = config.FAOSTAT_PRICES_SHA256
) -> Path:
    if downloads.is_verified(dest, expected_sha256):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    archive = dest.with_name("faostat_prices_bulk.zip.part")
    partial = dest.with_name(dest.name + ".part")
    try:
        downloads.fetch(BULK_URL, archive)
        extract_moldova(archive, partial)
    finally:
        archive.unlink(missing_ok=True)
    return downloads.accept(partial, dest, expected_sha256, f"{BULK_URL} (Moldova rows)")


def read_prices(path: Path = config.RAW_DIR / FILENAME) -> pd.DataFrame:
    """Columns: crop, year, usd_per_t."""
    prices = pd.read_csv(path, dtype={"Value": float, "Year": int})
    return pd.DataFrame(
        {
            "crop": prices["Item"].map(ITEMS),
            "year": prices["Year"],
            "usd_per_t": prices["Value"],
        }
    )
