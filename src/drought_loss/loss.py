"""Loss: hazard x exposure x vulnerability through CLIMADA, then the annual view of risk.

CLIMADA computes each crop's loss in each district and year. The annual view is built here, from
a year loss table, because it needs the crops added up year by year:

- AAL (average annual loss) is the mean of the annual losses. Means add, so the crops' AALs sum
  to the total.
- The exceedance curve gives the loss exceeded on average once every T years, from each year's
  total over all crops and districts (an aggregate, or AEP, view). Return-period losses do not
  add: the crops' worst years are not all the same year, so the sum of crop PMLs overstates the
  total's.
- No return period longer than the record is reported. From N years the worst year is all there
  is, and CLIMADA would quietly return it for any longer return period.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

RETURN_PERIODS = (2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000)


def crop_impact(hazard: Any, exposures: Any, functions: Any) -> Any:
    """CLIMADA's impact of one crop's hazard on its exposure, kept per event and district."""
    from climada.engine import ImpactCalc

    return ImpactCalc(exposures, functions, hazard).impact(save_mat=True, assign_centroids=True)


def year_loss_table(impacts: dict[str, Any], exposures: dict[str, Any]) -> pd.DataFrame:
    """Columns year, crop, district, loss_usd: every year, crop and district, zeros included."""
    parts = []
    for crop, impact in impacts.items():
        years = pd.Index([int(name) for name in impact.event_name], name="year")
        districts = pd.Index(exposures[crop].gdf["district"].to_numpy(), name="district")
        matrix = pd.DataFrame(impact.imp_mat.toarray(), index=years, columns=districts)
        long = matrix.stack().rename("loss_usd").reset_index()
        parts.append(long.assign(crop=crop))
    table = pd.concat(parts, ignore_index=True)
    return table[["year", "crop", "district", "loss_usd"]]


def annual_losses(table: pd.DataFrame) -> pd.Series:
    """Total loss per year, all crops and districts together."""
    return table.groupby("year")["loss_usd"].sum().rename("loss_usd")


def average_annual_loss(table: pd.DataFrame) -> pd.Series:
    """AAL per crop (US$): total loss over the record divided by its number of years."""
    n_years = table["year"].nunique()
    return (table.groupby("crop")["loss_usd"].sum() / n_years).rename("aal_usd")


def exceedance(annual: pd.Series, return_periods: Sequence[float]) -> pd.Series:
    """Loss exceeded on average once every T years, from N equally likely years.

    The same rule as CLIMADA's calc_freq_curve: the k-th largest loss is exceeded with frequency
    k / N, so its return period is N / k, with linear interpolation in between.
    """
    n = len(annual)
    too_long = [t for t in return_periods if t > n]
    if too_long:
        raise ValueError(
            f"return periods {too_long} are longer than the {n}-year record; "
            "a longer catalogue is needed for them"
        )
    descending = np.sort(annual.to_numpy(dtype=np.float64))[::-1]
    periods = n / np.arange(1, n + 1)
    losses = np.interp(return_periods, periods[::-1], descending[::-1])
    return pd.Series(losses, index=pd.Index(list(return_periods), name="return_period"))


def reportable(return_periods: Sequence[float], n_years: int) -> list[float]:
    return [t for t in return_periods if t <= n_years]


def by_district(table: pd.DataFrame, exposure_table: pd.DataFrame) -> pd.DataFrame:
    """AAL per district (all crops), its exposure, loss ratio and share of the national AAL."""
    n_years = table["year"].nunique()
    aal = table.groupby("district")["loss_usd"].sum() / n_years
    value = exposure_table.groupby("district")["value_usd"].sum()
    out = pd.DataFrame({"aal_usd": aal, "exposure_usd": value.reindex(aal.index)})
    out["loss_ratio"] = out["aal_usd"] / out["exposure_usd"]
    out["share_of_aal"] = out["aal_usd"] / out["aal_usd"].sum()
    return out.sort_values("aal_usd", ascending=False)


def commercial_share(exposure_table: pd.DataFrame) -> pd.Series:
    """Per crop: commercial value over all-producer value, the same in every district."""
    sums = exposure_table.groupby("crop")[["value_commercial_usd", "value_usd"]].sum()
    return (sums["value_commercial_usd"] / sums["value_usd"]).rename("commercial_share")


def commercial_annual_losses(table: pd.DataFrame, exposure_table: pd.DataFrame) -> pd.Series:
    """Annual losses counting commercial farms only.

    Loss is proportional to value within a crop, so each crop's loss scales by its commercial
    share before the crops are added up.
    """
    share = commercial_share(exposure_table)
    scaled = table["loss_usd"] * table["crop"].map(share)
    return scaled.groupby(table["year"]).sum().rename("loss_usd")


def bootstrap(
    annual: pd.Series, return_periods: Sequence[float], n: int, seed: int
) -> pd.DataFrame:
    """AAL and exceedance losses for `n` resamples of the record's years, with replacement.

    Shows how much a record of this length can pin down: years are drawn whole, so the spread is
    the sampling noise of having only these years.
    """
    rng = np.random.default_rng(seed)
    values = annual.to_numpy(dtype=np.float64)
    rows = []
    for _ in range(n):
        drawn = pd.Series(rng.choice(values, len(values), replace=True))
        rows.append([drawn.mean(), *exceedance(drawn, return_periods)])
    return pd.DataFrame(rows, columns=["aal", *return_periods])
