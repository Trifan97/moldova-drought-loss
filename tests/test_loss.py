"""The annual view of loss: exceedance, AAL, districts, and agreement with CLIMADA."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from drought_loss import config, hazard, loss, synthetic, vulnerability
from drought_loss.__main__ import compute_loss


def toy_table() -> pd.DataFrame:
    """Two crops, two districts, four years. Wheat's worst year is 2001, maize's is 2003."""
    rows = [
        (2000, "winter_wheat", "Cahul", 0.0),
        (2000, "winter_wheat", "Leova", 0.0),
        (2001, "winter_wheat", "Cahul", 60.0),
        (2001, "winter_wheat", "Leova", 20.0),
        (2002, "winter_wheat", "Cahul", 10.0),
        (2002, "winter_wheat", "Leova", 0.0),
        (2003, "winter_wheat", "Cahul", 0.0),
        (2003, "winter_wheat", "Leova", 10.0),
        (2000, "maize", "Cahul", 0.0),
        (2000, "maize", "Leova", 0.0),
        (2001, "maize", "Cahul", 0.0),
        (2001, "maize", "Leova", 0.0),
        (2002, "maize", "Cahul", 20.0),
        (2002, "maize", "Leova", 0.0),
        (2003, "maize", "Cahul", 50.0),
        (2003, "maize", "Leova", 30.0),
    ]
    return pd.DataFrame(rows, columns=["year", "crop", "district", "loss_usd"])


def test_exceedance_uses_rank_over_record_length() -> None:
    annual = pd.Series([float(v) for v in range(1, 11)])  # ten years, losses 1 to 10
    curve = loss.exceedance(annual, [10, 5, 2])
    # The k-th largest loss has return period 10 / k: 10 yr -> 10, 5 yr -> 9, 2 yr -> 6.
    assert list(curve) == [10.0, 9.0, 6.0]


def test_return_periods_longer_than_the_record_are_refused() -> None:
    annual = pd.Series(np.ones(60))
    with pytest.raises(ValueError, match="longer than the 60-year record"):
        loss.exceedance(annual, [50, 100])
    assert loss.reportable([50, 60, 100], 60) == [50, 60]


def test_aal_adds_up_across_crops_but_return_period_losses_do_not() -> None:
    table = toy_table()
    aal = loss.average_annual_loss(table)
    annual = loss.annual_losses(table)
    assert aal.sum() == pytest.approx(annual.mean())
    total = loss.exceedance(annual, [4])[4]
    by_crop = table.groupby(["crop", "year"])["loss_usd"].sum()
    summed = sum(loss.exceedance(by_crop.loc[c], [4])[4] for c in ["winter_wheat", "maize"])
    assert summed > total  # 80 + 80 against 80: the crops' worst years differ


def test_district_table_shares_the_national_aal() -> None:
    table = toy_table()
    exposure_table = pd.DataFrame(
        {
            "district": ["Cahul", "Leova", "Cahul", "Leova"],
            "crop": ["winter_wheat"] * 2 + ["maize"] * 2,
            "value_usd": [500.0, 500.0, 1000.0, 1000.0],
        }
    )
    districts = loss.by_district(table, exposure_table)
    assert districts.aal_usd.sum() == pytest.approx(loss.annual_losses(table).mean())
    assert districts.share_of_aal.sum() == pytest.approx(1.0)
    assert districts.loc["Cahul", "aal_usd"] == pytest.approx((60 + 10 + 20 + 50) / 4)
    assert districts.loc["Cahul", "loss_ratio"] == pytest.approx(35.0 / 1500.0)
    assert districts.index[0] == "Cahul"


def test_commercial_losses_scale_each_crop_by_its_commercial_share() -> None:
    table = toy_table()
    exposure_table = pd.DataFrame(
        {
            "crop": ["winter_wheat", "maize"],
            "value_usd": [100.0, 100.0],
            "value_commercial_usd": [90.0, 50.0],
        }
    )
    commercial = loss.commercial_annual_losses(table, exposure_table)
    assert commercial.loc[2001] == pytest.approx(0.9 * 80)
    assert commercial.loc[2003] == pytest.approx(0.9 * 10 + 0.5 * 80)


def test_bootstrap_is_repeatable_and_brackets_the_record() -> None:
    annual = pd.Series(np.random.default_rng(0).gamma(0.5, 10.0, 60))
    first = loss.bootstrap(annual, [10, 50], n=300, seed=1)
    pd.testing.assert_frame_equal(first, loss.bootstrap(annual, [10, 50], n=300, seed=1))
    low, high = first["aal"].quantile([0.05, 0.95])
    assert low < annual.mean() < high


def test_event_dates_continue_past_year_9999() -> None:
    assert hazard.event_ordinal(2012, 8) == date(2012, 8, 1).toordinal()
    ordinals = [hazard.event_ordinal(year, 8) for year in (9998, 9999, 10000, 11960)]
    assert ordinals == sorted(ordinals) and len(set(ordinals)) == 4
    assert hazard.event_ordinal(10000, 8) - hazard.event_ordinal(9999, 8) in (365, 366)


def test_provenance_round_trips_and_its_absence_is_an_error(tmp_path: Path) -> None:
    hazard.write_provenance(tmp_path, Path("stations.csv"), pd.Index([1961, 2020]))
    assert hazard.read_provenance(tmp_path) == {
        "spei_file": "stations.csv",
        "first_year": 1961,
        "last_year": 2020,
    }
    with pytest.raises(FileNotFoundError, match="rebuild"):
        hazard.read_provenance(tmp_path / "empty")


def test_losses_from_private_hazard_cannot_be_written_into_this_repository(tmp_path: Path) -> None:
    (tmp_path / hazard.PROVENANCE_FILENAME).write_text(
        json.dumps(
            {"spei_file": "master_dataset_v2_REAL.csv", "first_year": 1961, "last_year": 2020}
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="private data"):
        compute_loss(tmp_path, config.PROCESSED_DIR / "loss_leak")
    assert not (config.PROCESSED_DIR / "loss_leak").exists()


def test_generator_hazard_and_curve_agree_with_the_analytic_aal() -> None:
    # Interpolation is rescaled to keep SPEI standard normal at every district, so the long-run
    # loss ratio at a district between stations must approach the curve's analytic AAL ratio.
    run = synthetic.generate(3_000, seed=7)
    target = pd.DataFrame({"lat": [46.6], "lon": [28.5]}, index=pd.Index(["between"]))
    curve = vulnerability.calibrated_curves()["winter_wheat"]
    severity = hazard.crop_severity(run, target, "winter_wheat")["between"].to_numpy()
    simulated = np.mean(np.where(severity > 0, curve.loss(severity), 0.0))
    assert simulated == pytest.approx(vulnerability.average_annual_loss_ratio(curve), rel=0.15)


# --- agreement with CLIMADA -----------------------------------------------------------------


@pytest.fixture(scope="module")
def climada_run() -> dict[str, Any]:
    from climada.entity import Exposures

    severity = pd.DataFrame(
        np.random.default_rng(3).gamma(1.0, 0.7, size=(40, 2)),
        index=pd.Index(range(1981, 2021), name="year"),
        columns=pd.Index(["Cahul", "Leova"], name="district"),
    )
    severity[severity < 0.6] = 0.0
    targets = pd.DataFrame({"lat": [45.9, 46.5], "lon": [28.2, 28.3]}, index=severity.columns)
    crop_hazard = hazard.to_climada(severity, targets, "maize")
    exposures = Exposures(
        pd.DataFrame(
            {
                "latitude": targets.lat,
                "longitude": targets.lon,
                "value": [100.0, 50.0],
                "impf_DR": 3,
                "district": targets.index,
            }
        ),
        crs="EPSG:4326",
    )
    functions = vulnerability.impact_functions(vulnerability.calibrated_curves())
    impact = loss.crop_impact(crop_hazard, exposures, functions)
    table = loss.year_loss_table({"maize": impact}, {"maize": exposures})
    return {"impact": impact, "table": table, "hazard": crop_hazard, "severity": severity}


@pytest.mark.climada
def test_year_loss_table_holds_every_year_and_district(climada_run: dict[str, Any]) -> None:
    table = climada_run["table"]
    assert len(table) == 40 * 2
    np.testing.assert_allclose(loss.annual_losses(table).to_numpy(), climada_run["impact"].at_event)


@pytest.mark.climada
def test_aal_matches_climada(climada_run: dict[str, Any]) -> None:
    aal = loss.average_annual_loss(climada_run["table"])["maize"]
    assert aal == pytest.approx(climada_run["impact"].aai_agg)


@pytest.mark.climada
def test_exceedance_matches_climada_within_the_record(climada_run: dict[str, Any]) -> None:
    periods = [2, 5, 10, 20, 40]
    ours = loss.exceedance(loss.annual_losses(climada_run["table"]), periods)
    theirs = climada_run["impact"].calc_freq_curve(np.array(periods)).impact
    np.testing.assert_allclose(ours.to_numpy(), theirs)


@pytest.mark.climada
def test_climada_loss_equals_curve_times_value(climada_run: dict[str, Any]) -> None:
    curve = vulnerability.calibrated_curves()["maize"]
    severity = climada_run["severity"]
    expected = curve.loss(severity.to_numpy()) * np.array([100.0, 50.0])
    expected[severity.to_numpy() == 0] = 0.0
    matrix = climada_run["impact"].imp_mat
    assert sparse.issparse(matrix)
    np.testing.assert_allclose(matrix.toarray(), expected, atol=1e-9)
