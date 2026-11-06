"""The current-climate sensitivity: the shift's estimate, where it is applied, and its effect."""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from drought_loss import config, hazard, open_spei, synthetic, vulnerability

TARGETS = pd.DataFrame(
    {"lat": [47.00, 46.60, 48.40], "lon": [28.86, 28.50, 29.90]},
    index=pd.Index(["on_chisinau", "between", "far_northeast"], name="district"),
)


def test_shift_is_recent_mean_minus_full_record_mean() -> None:
    years = np.arange(1950, 2024)
    cells = pd.DataFrame(
        {
            "lat": 46.25,
            "lon": 28.75,
            "year": years,
            "month": 8,
            "spei_3": np.where(years >= 2001, -0.5, 0.0),
        }
    )
    expected = -0.5 - (-0.5 * 23 / 74)
    assert synthetic.recent_climate_shift(cells, 8, 2001) == pytest.approx(expected)


def test_each_year_counts_once_however_many_cells_report_it() -> None:
    rows = [
        (1990, 0.0),
        (2010, -1.0),
        (2010, -1.0),
        (2010, -1.0),
    ]  # three cells in 2010, one in 1990
    cells = pd.DataFrame(rows, columns=["year", "spei_3"]).assign(month=8, lat=46.0, lon=28.0)
    # Yearly means are 0 and -1, so the full-record mean is -0.5, not -0.75.
    assert synthetic.recent_climate_shift(cells, 8, 2001) == pytest.approx(-0.5)


def test_the_shift_moves_every_district_by_exactly_that_much() -> None:
    run = synthetic.generate(20, seed=3)
    base = hazard.crop_spei(run, TARGETS, "maize")
    shifted = hazard.crop_spei(run, TARGETS, "maize", shift=-0.6)
    np.testing.assert_allclose((shifted - base).to_numpy(), -0.6)
    severity = hazard.crop_severity(run, TARGETS, "maize", shift=-0.6)
    np.testing.assert_allclose(severity.to_numpy(), np.maximum(0.0, 0.6 - base.to_numpy()))


def test_a_drier_climate_raises_the_analytic_aal() -> None:
    curve = vulnerability.calibrated_curves()["maize"]
    stationary = vulnerability.average_annual_loss_ratio(curve)
    drier = vulnerability.average_annual_loss_ratio(curve, mean=-0.6)
    assert drier > stationary
    assert vulnerability.average_annual_loss_ratio(curve, mean=0.0) == pytest.approx(stationary)


def test_analytic_aal_with_a_shift_matches_shifted_samples() -> None:
    curve = vulnerability.calibrated_curves()["sunflower"]
    spei = np.random.default_rng(11).standard_normal(400_000) - 0.4
    simulated = np.mean(np.where(spei < 0, curve.loss(-spei), 0.0))
    assert simulated == pytest.approx(
        vulnerability.average_annual_loss_ratio(curve, -0.4), rel=0.02
    )


def test_provenance_records_the_climate_and_its_shifts(tmp_path: Path) -> None:
    hazard.write_provenance(
        tmp_path, Path("synthetic.csv"), pd.Index([1, 9]), "recent", config.RECENT_CLIMATE_SHIFT
    )
    record = json.loads((tmp_path / hazard.PROVENANCE_FILENAME).read_text(encoding="utf-8"))
    assert record["climate"] == "recent"
    assert record["spei_shift"] == config.RECENT_CLIMATE_SHIFT
    hazard.write_provenance(tmp_path, Path("synthetic.csv"), pd.Index([1, 9]))
    assert hazard.read_provenance(tmp_path)["spei_shift"] == {c: 0.0 for c in hazard.CROP_MONTHS}


def test_pinned_shifts_are_dry_and_cover_every_crop() -> None:
    assert set(config.RECENT_CLIMATE_SHIFT) == set(hazard.CROP_MONTHS)
    assert all(-1.0 < shift < 0.0 for shift in config.RECENT_CLIMATE_SHIFT.values())


@pytest.mark.data
def test_config_matches_shifts_from_the_open_cells() -> None:
    folder = os.environ.get("DROUGHT_LOSS_OPEN_SPEI")
    if not folder:
        pytest.skip("set DROUGHT_LOSS_OPEN_SPEI to the folder with the MD0*.xlsm cell workbooks")
    cells = open_spei.read_cells(Path(folder))
    for crop, month in hazard.CROP_MONTHS.items():
        shift = synthetic.recent_climate_shift(cells, month, config.RECENT_CLIMATE_FIRST_YEAR)
        assert shift == pytest.approx(config.RECENT_CLIMATE_SHIFT[crop], abs=5e-4), crop
