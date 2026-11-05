"""Crop-season drought hazard: station SPEI, then severity at each district, then a CLIMADA hazard.

One event per crop and year: the SPEI-3 that ends in the crop's most drought-sensitive month.
Severity is D = max(0, -SPEI-3), so zero means no drought. CLIMADA stores intensity as a sparse
matrix in which zero means "no hazard", and its exceedance tools assume larger is worse.
"""

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from scipy import sparse

from drought_loss import config, synthetic
from drought_loss.synthetic import FloatArray

HAZARD_TYPE = "DR"
# The month in which each crop's SPEI-3 is read: the end of its risk period in Moldova
# (Potopova et al. 2016, Int. J. Climatol. 36:2063, section 4.5 and Table 6). Winter wheat at
# anthesis and grain fill (April-June), sunflower at flowering and grain fill (May-July), maize
# from silking to milk (June-August).
CROP_MONTHS = {"winter_wheat": 6, "sunflower": 7, "maize": 8}


def station_table() -> pd.DataFrame:
    """The stations in config.py as a table: index station, columns lat and lon."""
    return pd.DataFrame.from_dict(
        config.STATIONS, orient="index", columns=["lat", "lon"]
    ).rename_axis("station")


def kriging_weights(
    stations: pd.DataFrame, targets: pd.DataFrame, range_km: float
) -> tuple[FloatArray, FloatArray]:
    """Simple-kriging weights (targets x stations), and the factor restoring unit variance.

    The weights are the best linear prediction of SPEI at each target from the stations, under
    the generator's correlation model. A weighted average of correlated N(0, 1) values has a
    variance below 1 between stations, which shrinks the extremes; with a convex loss curve that
    would understate loss. Dividing by the prediction's standard deviation keeps drought as
    frequent at a district as at a station.
    """
    lat = np.concatenate([stations["lat"].to_numpy(), targets["lat"].to_numpy()])
    lon = np.concatenate([stations["lon"].to_numpy(), targets["lon"].to_numpy()])
    corr = synthetic.correlation_matrix(lat, lon, range_km)
    n = len(stations)
    between_stations, station_to_target = corr[:n, :n], corr[:n, n:]
    weights = np.linalg.solve(between_stations, station_to_target)
    variance = np.sum(station_to_target * weights, axis=0)
    return np.asarray(weights.T, dtype=np.float64), 1.0 / np.sqrt(variance)


def interpolate(
    values: pd.DataFrame, stations: pd.DataFrame, targets: pd.DataFrame, range_km: float
) -> pd.DataFrame:
    """SPEI at each target (columns) for each event (rows), from station SPEI (columns).

    A station missing in a row is left out of that row only, with the weights recomputed from
    the stations that are present.
    """
    present = values.notna()
    empty = values.index[~present.any(axis=1)]
    if len(empty):
        raise ValueError(f"no station has data for: {list(empty)}")
    out = pd.DataFrame(np.nan, index=values.index, columns=targets.index)
    patterns = present.apply(tuple, axis=1)
    for pattern in patterns.unique():
        rows = patterns.index[patterns == pattern]
        used = values.columns[list(pattern)]
        weights, scale = kriging_weights(stations.loc[used], targets, range_km)
        out.loc[rows] = (values.loc[rows, used].to_numpy() @ weights.T) * scale
    return out


def crop_spei(
    station_spei: pd.DataFrame,
    targets: pd.DataFrame,
    crop: str,
    range_km: float = config.SYNTHETIC_RANGE_KM,
    sites: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """SPEI-3 in the crop's month at each target: rows are years, columns are targets.

    `sites` locates the values in the `station` column (index: that name, columns lat and lon);
    by default the 16 stations, but the open grid cells work the same way.

    Every year from the first to the last must appear, because each year becomes an event with
    the same probability; a year with no station data at all is an error, not a gap.
    """
    sites = station_table() if sites is None else sites
    month = CROP_MONTHS[crop]
    in_month = station_spei[station_spei["month"] == month]
    values = in_month.pivot(index="year", columns="station", values="spei_3")
    years = pd.RangeIndex(values.index.min(), values.index.max() + 1, name="year")
    values = values.reindex(years)
    return interpolate(values, sites.loc[values.columns], targets, range_km)


def crop_severity(
    station_spei: pd.DataFrame,
    targets: pd.DataFrame,
    crop: str,
    range_km: float = config.SYNTHETIC_RANGE_KM,
) -> pd.DataFrame:
    """Severity D = max(0, -SPEI-3) for one crop: rows are years, columns are targets."""
    return (-crop_spei(station_spei, targets, crop, range_km)).clip(lower=0.0)


def to_climada(severity: pd.DataFrame, targets: pd.DataFrame, crop: str) -> Any:
    """A CLIMADA hazard with one event per year, each with probability 1 / (number of years)."""
    # Imported here: CLIMADA takes half a minute to load, and nothing else in this module needs it.
    from climada.hazard import Centroids, Hazard

    years = [int(year) for year in severity.index]
    n = len(years)
    intensity = severity[targets.index].to_numpy(dtype=np.float64)
    return Hazard(
        haz_type=HAZARD_TYPE,
        units="-SPEI-3",
        centroids=Centroids(
            lat=targets["lat"].to_numpy(), lon=targets["lon"].to_numpy(), crs="EPSG:4326"
        ),
        event_id=np.arange(1, n + 1),
        event_name=[str(year) for year in years],
        date=np.array([date(year, CROP_MONTHS[crop], 1).toordinal() for year in years]),
        # Every year is equally likely: the record is treated as a sample of one, unchanging
        # climate. The README discusses what that assumption costs.
        frequency=np.full(n, 1.0 / n),
        frequency_unit="1/year",
        intensity=sparse.csr_matrix(intensity),
        fraction=sparse.csr_matrix((intensity > 0).astype(np.float64)),
    )


def describe(severity: pd.DataFrame) -> dict[str, float]:
    """Summary used by the command line: how often, how widely, and how badly it is dry."""
    values = severity.to_numpy(dtype=np.float64)
    return {
        "years": float(len(severity)),
        "share_dry": float(np.mean(values > 0)),
        "share_severe": float(np.mean(values >= 1.5)),
        "share_years_half_severe": synthetic.joint_drought_share(-values),
    }
