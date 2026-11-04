"""The synthetic generator produces SPEI with the properties it claims, and its fit works.

The statistical checks use fixed seeds, so they are deterministic. Each tolerance is a few
standard errors of the quantity being checked.
"""

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray
from scipy import stats

from drought_loss import config, synthetic

N_YEARS = 2_000
N_STATIONS = len(config.STATIONS)


@pytest.fixture(scope="module")
def long_run() -> pd.DataFrame:
    return synthetic.generate(N_YEARS, seed=1)


def wide(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    return frame.pivot_table(index=["year", "month"], columns="station", values=column)


def station_coords() -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    names = sorted(config.STATIONS)
    lat = np.array([config.STATIONS[n][0] for n in names])
    lon = np.array([config.STATIONS[n][1] for n in names])
    return lat, lon


def test_one_degree_of_latitude_is_about_111_km() -> None:
    d = synthetic.distance_km(np.array([47.0, 48.0]), np.array([28.0, 28.0]))
    assert d[0, 1] == pytest.approx(111.19, abs=0.05)
    assert d[0, 0] == 0.0
    np.testing.assert_allclose(d, d.T)


def test_correlation_matrix_is_valid_and_falls_with_distance() -> None:
    lat, lon = station_coords()
    corr = synthetic.correlation_matrix(lat, lon, 600.0)
    np.testing.assert_allclose(np.diag(corr), 1.0)
    np.linalg.cholesky(corr)  # raises unless positive definite
    dist = synthetic.distance_km(lat, lon)
    upper = np.triu_indices(len(lat), 1)
    order = np.argsort(dist[upper])
    assert np.all(np.diff(corr[upper][order]) <= 0)


@pytest.mark.parametrize(
    ("k", "lag1", "expected"),
    [(1, 0.4, 1.0), (3, 0.0, np.sqrt(3.0)), (3, 0.5, np.sqrt(3 + 2 * 2 * 0.5 + 2 * 0.25))],
)
def test_accumulation_sd(k: int, lag1: float, expected: float) -> None:
    assert synthetic.accumulation_sd(k, lag1) == pytest.approx(expected)


def test_output_has_one_row_per_station_and_month(long_run: pd.DataFrame) -> None:
    assert len(long_run) == N_YEARS * 12 * N_STATIONS
    assert list(long_run.columns) == ["station", "lat", "lon", "year", "month", "spei_1", "spei_3"]
    assert not long_run.duplicated(["station", "year", "month"]).any()
    first = long_run.groupby("station").head(2)
    assert first.spei_3.isna().all()  # no complete 3-month window yet
    assert long_run.spei_3.isna().sum() == 2 * N_STATIONS


def test_station_coordinates_travel_with_their_station(long_run: pd.DataFrame) -> None:
    coords = long_run.drop_duplicates("station").set_index("station")[["lat", "lon"]]
    for name, (lat, lon) in config.STATIONS.items():
        assert tuple(coords.loc[name]) == (lat, lon)


def test_same_seed_same_output_and_new_seed_new_output() -> None:
    a = synthetic.generate(5, seed=7)
    pd.testing.assert_frame_equal(a, synthetic.generate(5, seed=7))
    assert not np.allclose(a.spei_1, synthetic.generate(5, seed=8).spei_1)


@pytest.mark.parametrize("column", ["spei_1", "spei_3"])
def test_every_station_and_month_is_standard_normal(long_run: pd.DataFrame, column: str) -> None:
    # The dashboard's generator failed exactly here: its "SPEI" kept a seasonal cycle.
    grouped = long_run.groupby(["station", "month"])[column]
    standard_error = 1 / np.sqrt(N_YEARS)
    assert grouped.mean().abs().max() < 5 * standard_error
    assert (grouped.std() - 1).abs().max() < 0.08


def test_drought_frequency_matches_the_normal_distribution(long_run: pd.DataFrame) -> None:
    for column in ["spei_1", "spei_3"]:
        share = (long_run[column] <= -1.5).sum() / long_run[column].notna().sum()
        assert share == pytest.approx(stats.norm.cdf(-1.5), abs=0.004)


def test_spatial_correlation_matches_the_model(long_run: pd.DataFrame) -> None:
    by_station = wide(long_run, "spei_1")
    lat, lon = station_coords()  # sorted names, like the pivot's columns
    expected = synthetic.correlation_matrix(lat, lon, config.SYNTHETIC_RANGE_KM)
    assert list(by_station.columns) == sorted(config.STATIONS)
    np.testing.assert_allclose(by_station.corr().to_numpy(), expected, atol=0.02)


def test_persistence_matches_the_ar1_model(long_run: pd.DataFrame) -> None:
    rho = config.SYNTHETIC_LAG1
    spei1, spei3 = wide(long_run, "spei_1"), wide(long_run, "spei_3")
    assert np.mean([spei1[s].autocorr(1) for s in spei1]) == pytest.approx(rho, abs=0.01)

    def cov(h: int) -> float:
        return float(sum(rho ** abs(i - j + h) for i in range(3) for j in range(3)))

    lag1_spei3 = np.mean([spei3[s].autocorr(1) for s in spei3])
    assert lag1_spei3 == pytest.approx(cov(1) / cov(0), abs=0.01)


def test_spei3_is_the_standardised_three_month_sum_of_spei1(long_run: pd.DataFrame) -> None:
    one = long_run[long_run.station == "Chisinau"]
    rolling = one.spei_1.rolling(3).sum() / synthetic.accumulation_sd(3, config.SYNTHETIC_LAG1)
    np.testing.assert_allclose(one.spei_3.to_numpy(), rolling.to_numpy(), equal_nan=True)


def test_calibration_recovers_known_parameters() -> None:
    sites = {f"site{i}": (45.75 + 0.5 * (i // 6), 26.75 + 0.5 * (i % 6)) for i in range(18)}
    frame = synthetic.generate(1_500, seed=3, range_km=450.0, lag1=0.25, sites=sites)
    fit = synthetic.calibrate(frame)
    assert fit.range_km == pytest.approx(450.0, rel=0.06)
    assert fit.lag1 == pytest.approx(0.25, abs=0.01)
    assert fit.n_sites == 18


def test_fit_does_not_depend_on_column_order() -> None:
    sites = {f"site{i}": (45.75 + 0.5 * (i // 4), 27.0 + 0.5 * (i % 4)) for i in range(12)}
    by_site = synthetic.by_site(synthetic.generate(300, seed=4, sites=sites), "spei_1")
    shuffled = by_site[by_site.columns[np.random.default_rng(0).permutation(by_site.shape[1])]]
    expected = synthetic.fit_range_km(*synthetic.pairwise_correlation(by_site))
    # Shuffling changes only the order of floating-point additions. Pairing distances with the
    # wrong correlations instead sends the fit to its 20,000 km bound.
    actual = synthetic.fit_range_km(*synthetic.pairwise_correlation(shuffled))
    assert actual == pytest.approx(expected, rel=1e-9)


def test_gaps_in_the_months_are_refused() -> None:
    frame = synthetic.generate(3, seed=5, sites={"a": (47.0, 28.0), "b": (46.0, 29.0)})
    with pytest.raises(ValueError, match="not consecutive"):
        synthetic.by_site(frame[frame.month != 6], "spei_1")


def test_joint_drought_share_counts_years_where_most_sites_are_dry() -> None:
    values = np.array([[-2.0, -1.6, 0.0], [-1.5, 0.3, 0.2], [-1.7, -1.5, -3.0], [0.0, 0.0, 0.0]])
    assert synthetic.joint_drought_share(values) == pytest.approx(2 / 4)
    assert synthetic.joint_drought_share(values, fraction=1.0) == pytest.approx(1 / 4)
