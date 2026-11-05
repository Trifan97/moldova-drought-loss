"""Paths, pinned inputs, station locations and the synthetic generator's calibrated parameters."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

# Files from the private real-data track follow this naming convention. The pipeline refuses to
# write results from them inside this repository, and a test refuses to let them be committed.
PRIVATE_NAME = re.compile(r"_real(\.|_|$)", re.IGNORECASE)

# Moldova's districts: geoBoundaries ADM1, 37 units (CC BY 3.0 IGO). The URL names a fixed
# commit, and the SHA-256 is checked on every read, so a fresh clone gets the identical file.
BOUNDARIES_URL = (
    "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/"
    "releaseData/gbOpen/MDA/ADM1/geoBoundaries-MDA-ADM1.geojson"
)
BOUNDARIES_FILENAME = "geoBoundaries-MDA-ADM1.geojson"
BOUNDARIES_SHA256 = "2358d3f23e7199eb8296d8859c09640c4db9f0a9cef31a429708015ee0aea9b6"

# NBS crop statistics (PX-Web responses) and Moldova's FAOSTAT producer prices, as fetched by
# `python -m drought_loss download` on 2026-11-04. A revision by either source changes the hash
# and stops the download, so results never move without a reviewed update here.
NBS_DISTRICT_SHA256 = "1d2ddfe51623dc9c32d38e2c64ec18d46988f21fcdf52dbe2d7cf4b2b3ce0a98"
NBS_NATIONAL_SHA256 = "7366c483704aaefaae25fb320fb5eee19a734ac269aa5079adc7a01df5a1efd1"
FAOSTAT_PRICES_SHA256 = "0c9c850785ca8cc2d3ae5b26ec7b9fdec9235dc1235f95cb768bda00aac0830d"

# Moldova's 16 meteorological stations, at the rounded public locations already used by the
# public MD_Drought_Intel dashboard. Camenca, Dubasari, Rabnita and Tiraspol are on the left
# bank of the Nistru: they shape the hazard field, but the exposure statistics exclude that
# area (see the README).
STATIONS: dict[str, tuple[float, float]] = {
    "Baltata": (47.25, 28.75),
    "Balti": (47.76, 27.93),
    "Bravicea": (47.22, 28.37),
    "Briceni": (48.37, 27.07),
    "Cahul": (45.90, 28.19),
    "Camenca": (48.02, 28.70),
    "Ceadir-Lunga": (46.07, 28.83),
    "Chisinau": (47.00, 28.86),
    "Comrat": (46.30, 28.67),
    "Cornesti": (47.35, 27.98),
    "Dubasari": (47.27, 29.15),
    "Falesti": (47.57, 27.72),
    "Leova": (46.48, 28.25),
    "Rabnita": (47.75, 29.00),
    "Soroca": (48.15, 28.30),
    "Tiraspol": (46.85, 29.60),
}

# Synthetic generator parameters, fitted by `python -m drought_loss calibrate` to 18 cells of
# CSIC's Global 0.5 degree SPEI database over Moldova (per-location exports from spei.csic.es,
# downloaded November 2023, January 1950 to September 2023; Open Database License). They come
# from open data only, never from the station records, so the public track stays clean-room.
#
# Correlation range: exp(-distance / range), fitted on April-August SPEI-1, the months behind
# the June-August SPEI-3 crop windows. Summer rain is patchier, so this is shorter than the
# all-month fit (about 740 km) and the winter fit (about 900 km).
SYNTHETIC_RANGE_KM = 605.0
# Lag-1 autocorrelation of monthly SPEI-1, averaged over cells and months.
SYNTHETIC_LAG1 = 0.103
SYNTHETIC_SEED = 42

# Impact functions, fitted by `python -m drought_loss vulnerability --cells <folder>` on public
# data only: NBS district yields over their Theil-Sen trend, against SPEI-3 from the same open
# CSIC cells, 2007-2023. Per crop: anomaly = a + b SPEI + c SPEI^2, used up to the largest
# severity in the data (see vulnerability.py for how loss follows from it).
#                  a         b         c         largest severity
VULNERABILITY_CURVES: dict[str, tuple[float, float, float, float]] = {
    "winter_wheat": (0.0706, 0.1233, -0.0237, 1.98),
    "sunflower": (0.1386, 0.0982, -0.0296, 2.86),
    "maize": (0.5752, 0.4303, -0.0204, 2.84),
}
# Each fitted curve's loss is multiplied by this factor so that its mean loss over years with
# SPEI-3 <= -1 (SPEI standard normal) equals Potopova et al. (2016, Table 6), from station SPEI.
# Gridded SPEI flattens a fitted curve (regression dilution); the anchor restores its level.
# Computed from the rounded curves above, which are what the model runs on.
VULNERABILITY_ANCHOR_SCALE: dict[str, float] = {
    "winter_wheat": 1.141,
    "sunflower": 2.612,
    "maize": 2.225,
}
# Yield scatter around each curve: standard deviation, and the mean correlation of that scatter
# between districts in the same year.
VULNERABILITY_RESIDUALS: dict[str, tuple[float, float]] = {
    "winter_wheat": (0.272, 0.72),
    "sunflower": (0.229, 0.54),
    "maize": (0.452, 0.52),
}
