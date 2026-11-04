"""Clean-room synthetic SPEI for the public track.

SPEI is defined to be standard normal in every calendar month, so the generator works in that
space directly. Simulating rainfall and then standardising it would bring back the
distribution-fitting problems that broke the dashboard's generator: skewed sums, and a
log-logistic fit that fails on negative skew.

The model, chosen from the open 0.5 degree cells over Moldova:

- monthly SPEI-1 is a Gaussian field, correlated as exp(-distance / range) between sites and
  AR(1) in time with one coefficient everywhere (a separable model);
- SPEI-k is the k-month sum of SPEI-1 divided by its exact standard deviation, so it is exactly
  N(0, 1) and consistent with SPEI-1 by construction.

What it leaves out is listed in the README: no climate trend, no tail dependence beyond the
Gaussian, and one persistence coefficient for every month.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy import optimize

from drought_loss import config

FloatArray = NDArray[np.float64]

EARTH_RADIUS_KM = 6371.0
# The months behind the June-August SPEI-3 crop windows; the correlation range is fitted on these.
GROWING_SEASON = (4, 5, 6, 7, 8)


def distance_km(lat: FloatArray, lon: FloatArray) -> FloatArray:
    """Great-circle (haversine) distance between every pair of sites."""
    phi, lam = np.radians(lat), np.radians(lon)
    dphi = phi[:, None] - phi[None, :]
    dlam = lam[:, None] - lam[None, :]
    h = np.sin(dphi / 2) ** 2 + np.cos(phi[:, None]) * np.cos(phi[None, :]) * np.sin(dlam / 2) ** 2
    return np.asarray(2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(h)), dtype=np.float64)


def correlation_matrix(lat: FloatArray, lon: FloatArray, range_km: float) -> FloatArray:
    """exp(-d / range): a valid (positive definite) correlation for great-circle distance."""
    return np.asarray(np.exp(-distance_km(lat, lon) / range_km), dtype=np.float64)


def accumulation_sd(k: int, lag1: float) -> float:
    """Standard deviation of the sum of k consecutive values of a unit-variance AR(1) series."""
    lags = np.abs(np.subtract.outer(np.arange(k), np.arange(k)))
    return float(np.sqrt(np.sum(lag1**lags)))


def simulate_spei1(
    n_months: int, corr: FloatArray, lag1: float, rng: np.random.Generator
) -> FloatArray:
    """Monthly SPEI-1, shape (months, sites).

    The first month is drawn from the stationary distribution, so no burn-in is needed: every
    month is N(0, corr) across sites.
    """
    chol = np.linalg.cholesky(corr)
    shocks = rng.standard_normal((n_months, corr.shape[0])) @ chol.T
    spei1 = np.empty_like(shocks)
    spei1[0] = shocks[0]
    # Scaling the new shock by sqrt(1 - lag1^2) keeps the variance at 1 every month.
    scale = np.sqrt(1.0 - lag1**2)
    for t in range(1, n_months):
        spei1[t] = lag1 * spei1[t - 1] + scale * shocks[t]
    return spei1


def accumulate(spei1: FloatArray, k: int, lag1: float) -> FloatArray:
    """SPEI-k from SPEI-1: k-month sums divided by their exact standard deviation.

    The first k - 1 months have no complete window and are NaN, as in observed SPEI.
    """
    n = spei1.shape[0]
    out = np.full_like(spei1, np.nan)
    windows = np.sum([spei1[k - 1 - j : n - j] for j in range(k)], axis=0)
    out[k - 1 :] = windows / accumulation_sd(k, lag1)
    return out


def generate(
    n_years: int,
    seed: int,
    *,
    range_km: float = config.SYNTHETIC_RANGE_KM,
    lag1: float = config.SYNTHETIC_LAG1,
    sites: Mapping[str, tuple[float, float]] = config.STATIONS,
    first_year: int = 1961,
) -> pd.DataFrame:
    """Synthetic monthly SPEI, one row per site and month.

    Columns: station, lat, lon, year, month, spei_1, spei_3. Station records start in 1961,
    hence the default first year; for a long catalogue the years are just labels.
    """
    names = list(sites)
    lat = np.array([sites[name][0] for name in names], dtype=np.float64)
    lon = np.array([sites[name][1] for name in names], dtype=np.float64)
    n_months = n_years * 12
    spei1 = simulate_spei1(
        n_months, correlation_matrix(lat, lon, range_km), lag1, np.random.default_rng(seed)
    )
    spei3 = accumulate(spei1, 3, lag1)
    months = np.arange(n_months)
    n_sites = len(names)
    # Arrays are (months, sites); ravel walks every site within a month before the next month.
    return pd.DataFrame(
        {
            "station": np.tile(names, n_months),
            "lat": np.tile(lat, n_months),
            "lon": np.tile(lon, n_months),
            "year": np.repeat(first_year + months // 12, n_sites),
            "month": np.repeat(months % 12 + 1, n_sites),
            "spei_1": spei1.ravel(),
            "spei_3": spei3.ravel(),
        }
    )


@dataclass(frozen=True)
class Calibration:
    range_km: float
    lag1: float
    n_sites: int
    first_month: str
    last_month: str


def by_site(cells: pd.DataFrame, column: str) -> pd.DataFrame:
    """One column per site, labelled (lat, lon), and one row per consecutive month."""
    wide = cells.pivot_table(index=["year", "month"], columns=["lat", "lon"], values=column)
    wide = wide.sort_index()
    month_number = wide.index.get_level_values("year") * 12 + wide.index.get_level_values("month")
    if not np.all(np.diff(month_number) == 1):
        raise ValueError("months are not consecutive, so lag-1 autocorrelation would be wrong")
    return wide


def pairwise_correlation(wide: pd.DataFrame) -> tuple[FloatArray, FloatArray]:
    """Distance and correlation for every pair of sites in a table labelled by (lat, lon).

    The coordinates come from the column labels themselves, so the distances cannot fall out of
    step with the correlations. Pairing them by position once made the fitted range meaningless.
    """
    coords = np.array(wide.columns.tolist(), dtype=np.float64)
    upper = np.triu_indices(len(coords), 1)
    distances = distance_km(coords[:, 0], coords[:, 1])[upper]
    correlations = wide.corr().to_numpy(dtype=np.float64)[upper]
    return distances, correlations


def fit_range_km(distances: FloatArray, correlations: FloatArray) -> float:
    """Least-squares range of exp(-d / range).

    One parameter only: with a free sill (a nugget), the fit on the Moldova cells put the sill
    at 1, so the simpler model loses nothing.
    """
    result = optimize.minimize_scalar(
        lambda r: float(np.sum((correlations - np.exp(-distances / r)) ** 2)),
        bounds=(10.0, 20_000.0),
        method="bounded",
    )
    return float(result.x)


def fit_lag1(wide: pd.DataFrame) -> float:
    """Lag-1 autocorrelation averaged over sites; rows must be consecutive months."""
    return float(np.mean([wide[column].autocorr(1) for column in wide.columns]))


def calibrate(cells: pd.DataFrame) -> Calibration:
    """Fit the generator to observed SPEI-1 (columns lat, lon, year, month, spei_1)."""
    wide = by_site(cells, "spei_1")
    summer = wide[wide.index.get_level_values("month").isin(GROWING_SEASON)]
    first, last = wide.index[0], wide.index[-1]
    return Calibration(
        range_km=fit_range_km(*pairwise_correlation(summer)),
        lag1=fit_lag1(wide),
        n_sites=wide.shape[1],
        first_month=f"{first[0]}-{first[1]:02d}",
        last_month=f"{last[0]}-{last[1]:02d}",
    )


def joint_drought_share(
    values: pd.DataFrame | FloatArray, threshold: float = -1.5, fraction: float = 0.5
) -> float:
    """Share of rows (years) in which at least `fraction` of sites are at or below `threshold`.

    This is the property that drives the national loss tail: losses only add up to a large
    national total when many places are dry in the same year.
    """
    dry = np.asarray(values, dtype=np.float64) <= threshold
    return float(np.mean(dry.mean(axis=1) >= fraction))
