"""Monthly station SPEI from a CSV, checked before it reaches the hazard.

The same reader takes the synthetic CSV and, from the private repository, the real station
file, so both tracks enter the pipeline through one door.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from drought_loss import config

COLUMNS = ["station", "year", "month", "spei_3"]


def validate(frame: pd.DataFrame) -> None:
    """Raise ValueError unless the table can feed the hazard.

    Missing station-months are allowed: the hazard leaves an absent station out of that
    year's interpolation. Wrong structure is not.
    """
    missing = [column for column in COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    unknown = sorted(set(frame.station) - set(config.STATIONS))
    if unknown:
        raise ValueError(f"stations not in config.STATIONS: {unknown}")
    if not frame.month.between(1, 12).all():
        raise ValueError("month must be 1 to 12")
    if frame.duplicated(["station", "year", "month"]).any():
        raise ValueError("more than one row for a station and month")
    if np.isinf(frame.spei_3).any():
        raise ValueError("spei_3 holds infinite values")


def read_station_spei(path: Path) -> pd.DataFrame:
    """Columns station, year, month, spei_3; any other columns in the file are ignored."""
    frame = pd.read_csv(path, usecols=lambda column: column in COLUMNS)
    validate(frame)
    return frame[COLUMNS].sort_values(["station", "year", "month"]).reset_index(drop=True)


def check_output_location(spei_path: Path, out_dir: Path) -> None:
    """Refuse to write results from private data anywhere inside this public repository.

    The git guard would still stop a commit, but results should never sit next to public code
    at all, where one mistyped `git add -f` would publish them.
    """
    inside = out_dir.resolve().is_relative_to(config.REPO_ROOT.resolve())
    if config.PRIVATE_NAME.search(spei_path.name) and inside:
        raise SystemExit(
            f"{spei_path.name} is private data, so its results cannot go to {out_dir}, inside the "
            "public repository. Run from the private repository and pass --out there."
        )
