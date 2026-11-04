"""Paths, station locations and the synthetic generator's calibrated parameters."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

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

# Synthetic generator parameters, fitted by `python -m drought_loss calibrate` to 18 open
# 0.5 degree SPEI cells over Moldova (January 1950 to September 2023). They come from open
# data only, never from the station records, so the public track stays clean-room.
# The exact CSIC product behind the cell files is still to be confirmed (see the README).
#
# Correlation range: exp(-distance / range), fitted on April-August SPEI-1, the months behind
# the June-August SPEI-3 crop windows. Summer rain is patchier, so this is shorter than the
# all-month fit (about 740 km) and the winter fit (about 900 km).
SYNTHETIC_RANGE_KM = 605.0
# Lag-1 autocorrelation of monthly SPEI-1, averaged over cells and months.
SYNTHETIC_LAG1 = 0.103
SYNTHETIC_SEED = 42
