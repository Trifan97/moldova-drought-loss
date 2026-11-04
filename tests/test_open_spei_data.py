"""The parameters in config.py can be re-derived from the open SPEI cells.

The cell workbooks are not downloadable by the pipeline, so these tests run only when
DROUGHT_LOSS_OPEN_SPEI points at their folder, and are skipped with the reason otherwise.
"""

import os
from pathlib import Path

import pandas as pd
import pytest

from drought_loss import config, open_spei, synthetic

pytestmark = pytest.mark.data


@pytest.fixture(scope="module")
def cells() -> pd.DataFrame:
    folder = os.environ.get("DROUGHT_LOSS_OPEN_SPEI")
    if not folder:
        pytest.skip("set DROUGHT_LOSS_OPEN_SPEI to the folder with the MD0*.xlsm cell workbooks")
    return open_spei.read_cells(Path(folder))


def test_all_eighteen_cells_over_moldova_are_read(cells: pd.DataFrame) -> None:
    coords = cells[["lat", "lon"]].drop_duplicates()
    assert len(coords) == 18
    assert coords.lat.between(45.25, 48.75).all() and coords.lon.between(26.25, 30.25).all()


def test_cells_are_standardised_spei(cells: pd.DataFrame) -> None:
    monthly = cells.groupby("month").spei_1
    assert monthly.mean().abs().max() < 0.2
    assert (monthly.std() - 1).abs().max() < 0.1


def test_config_matches_a_fresh_calibration(cells: pd.DataFrame) -> None:
    fit = synthetic.calibrate(cells)
    # config.py stores the fit rounded: the range to 1 km, lag-1 to 3 decimals.
    assert abs(fit.range_km - config.SYNTHETIC_RANGE_KM) < 0.5
    assert abs(fit.lag1 - config.SYNTHETIC_LAG1) < 0.0005
