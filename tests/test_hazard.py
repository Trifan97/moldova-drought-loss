"""Station SPEI becomes crop-season severity at each district, and then a CLIMADA hazard."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from drought_loss import config, hazard, synthetic

RANGE = config.SYNTHETIC_RANGE_KM
# Two targets on stations (exact answers known) and two off them.
TARGETS = pd.DataFrame(
    {"lat": [47.00, 45.90, 46.60, 48.40], "lon": [28.86, 28.19, 28.50, 29.90]},
    index=pd.Index(["on_chisinau", "on_cahul", "between", "far_northeast"], name="district"),
)


@pytest.fixture(scope="module")
def august() -> pd.DataFrame:
    run = synthetic.generate(3_000, seed=11)
    return run[run.month == 8].pivot(index="year", columns="station", values="spei_3")


def stations_for(values: pd.DataFrame) -> pd.DataFrame:
    return hazard.station_table().loc[values.columns]


def test_a_district_on_a_station_takes_that_station_exactly() -> None:
    weights, scale = hazard.kriging_weights(hazard.station_table(), TARGETS.iloc[:1], RANGE)
    expected = (hazard.station_table().index == "Chisinau").astype(float)
    np.testing.assert_allclose(weights[0], expected, atol=1e-9)
    assert scale[0] == pytest.approx(1.0)


def test_interpolation_alone_would_shrink_the_extremes_away_from_stations() -> None:
    # scale is 1 / standard deviation of the plain kriging prediction: above 1 means shrinkage,
    # and the further from the stations, the more.
    _, scale = hazard.kriging_weights(hazard.station_table(), TARGETS, RANGE)
    assert scale[2] > 1.0
    assert scale[3] > scale[2]


def test_rescaling_keeps_drought_as_frequent_at_districts_as_at_stations(
    august: pd.DataFrame,
) -> None:
    spei = hazard.interpolate(august, stations_for(august), TARGETS, RANGE)
    for name in TARGETS.index:
        assert spei[name].mean() == pytest.approx(0.0, abs=0.06)
        assert spei[name].std() == pytest.approx(1.0, abs=0.04)
        assert (spei[name] <= -1.5).mean() == pytest.approx(stats.norm.cdf(-1.5), abs=0.015)


def test_a_missing_station_is_left_out_of_that_year_only(august: pd.DataFrame) -> None:
    values = august.head(4).copy()
    gap_year, full_year = values.index[1], values.index[0]
    values.loc[gap_year, "Chisinau"] = np.nan
    spei = hazard.interpolate(values, stations_for(values), TARGETS, RANGE)
    assert spei.notna().all().all()

    rest = values.columns.drop("Chisinau")
    weights, scale = hazard.kriging_weights(stations_for(values[rest]), TARGETS, RANGE)
    expected_gap = (values.loc[[gap_year], rest].to_numpy() @ weights.T) * scale
    np.testing.assert_allclose(spei.loc[[gap_year]].to_numpy(), expected_gap)

    weights, scale = hazard.kriging_weights(stations_for(values), TARGETS, RANGE)
    expected_full = (values.loc[[full_year]].to_numpy() @ weights.T) * scale
    np.testing.assert_allclose(spei.loc[[full_year]].to_numpy(), expected_full)


def test_a_year_with_no_station_data_is_refused(august: pd.DataFrame) -> None:
    values = august.head(3).copy()
    values.loc[values.index[2]] = np.nan
    with pytest.raises(ValueError, match="no station has data"):
        hazard.interpolate(values, stations_for(values), TARGETS, RANGE)


def uniform_spei(by_month: dict[int, float], years: tuple[int, ...] = (2001, 2002)) -> pd.DataFrame:
    """Every station gets the same SPEI-3, set per month; unlisted months are wet (+0.5)."""
    rows = [
        (name, year, month, by_month.get(month, 0.5))
        for name in config.STATIONS
        for year in years
        for month in range(1, 13)
    ]
    return pd.DataFrame(rows, columns=["station", "year", "month", "spei_3"])


def test_each_crop_reads_its_own_month_and_severity_is_minus_spei_when_dry() -> None:
    frame = uniform_spei({6: -1.0, 8: -2.0})
    on_stations = TARGETS.iloc[:2]
    expected = {"winter_wheat": 1.0, "sunflower": 0.0, "maize": 2.0}
    for crop, severity in expected.items():
        result = hazard.crop_severity(frame, on_stations, crop)
        np.testing.assert_allclose(result.to_numpy(), severity, atol=1e-9)


def test_a_missing_year_inside_the_record_is_refused() -> None:
    frame = uniform_spei({8: -2.0}, years=(2001, 2002, 2003))
    without_2002_august = frame[~((frame.year == 2002) & (frame.month == 8))]
    with pytest.raises(ValueError, match="no station has data"):
        hazard.crop_severity(without_2002_august, TARGETS, "maize")


def test_describe_counts_dry_severe_and_widespread() -> None:
    severity = pd.DataFrame([[0.0, 0.5], [1.5, 2.0], [0.0, 0.0], [1.6, 0.0]])
    summary = hazard.describe(severity)
    assert summary["share_dry"] == pytest.approx(4 / 8)
    assert summary["share_severe"] == pytest.approx(3 / 8)
    assert summary["share_years_half_severe"] == pytest.approx(2 / 4)


@pytest.mark.climada
def test_climada_hazard_has_one_event_per_year_in_the_crop_month() -> None:
    severity = pd.DataFrame(
        [[0.0, 1.2], [2.0, 0.0], [0.0, 0.0]],
        index=pd.Index([1961, 1962, 1963], name="year"),
        columns=TARGETS.index[:2],
    )
    built = hazard.to_climada(severity, TARGETS.iloc[:2], "maize")
    built.check()
    assert built.haz_type == "DR"
    assert list(built.event_name) == ["1961", "1962", "1963"]
    assert built.frequency.sum() == pytest.approx(1.0)
    np.testing.assert_allclose(built.intensity.toarray(), severity.to_numpy())
    assert {date.fromordinal(int(d)).month for d in built.date} == {8}
    np.testing.assert_allclose(built.centroids.lat, TARGETS.lat.iloc[:2])
