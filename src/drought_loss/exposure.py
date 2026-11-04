"""Exposure: the value of each crop's expected harvest in each district, in US dollars.

value = sown area x expected yield x scale-up to all producers x producer price

- Sown area: mean of the latest five years, so the model asks "what would a drought do to
  today's farms?" (an "as-if" exposure held fixed against every year of the hazard record).
- Expected yield: the median of the latest ten years. The vulnerability curve measures loss
  against typical yield, so a good-year yield here would count drought twice.
- Scale-up: the district table only covers enterprises and farms of 10 ha or more. Each crop
  is scaled by national all-producer production over the district table's national total,
  which assumes smallholders grow each crop in the same places as large farms.
- Price: FAOSTAT producer price, mean of the latest five years, in nominal US dollars.

The commercial-only value (without the scale-up) is kept too, because insurance mostly
reaches commercial farms.
"""

from typing import Any

import numpy as np
import pandas as pd

from drought_loss import nbs

AREA_YEARS = range(2021, 2026)
YIELD_YEARS = range(2016, 2026)
PRICE_YEAR_COUNT = 5
# One impact function per crop; the id ties each crop's exposure to its own curve.
IMPACT_FUNCTION_IDS = {"winter_wheat": 1, "sunflower": 2, "maize": 3}


def scale_to_all_producers(district: pd.DataFrame, national: pd.DataFrame) -> pd.Series:
    """Per crop: national production by all producers / the district table's national total.

    Summed over the years both tables cover, so one drought year cannot set the ratio.
    """
    years = sorted(set(district["year"]) & set(national["year"]))
    whole = district[(district["code"] == nbs.WHOLE_COUNTRY) & district["year"].isin(years)]
    everyone = national[(national["category"] == "all") & national["year"].isin(years)]
    ratio = (
        everyone.groupby("crop")["production_t"].sum() / whole.groupby("crop")["harvest_t"].sum()
    )
    return ratio.rename("scale")


def recent_prices(prices: pd.DataFrame, n_years: int = PRICE_YEAR_COUNT) -> pd.Series:
    """Per crop: mean producer price over the latest `n_years` years with data (US$ per tonne)."""
    latest = prices.sort_values("year").groupby("crop").tail(n_years)
    return latest.groupby("crop")["usd_per_t"].mean().rename("price_usd_t")


def build(district: pd.DataFrame, national: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """One row per district and crop, with every factor of the value kept for inspection."""
    rows = district[district["code"].isin(nbs.DISTRICTS)]
    area = rows[rows["year"].isin(AREA_YEARS)].groupby(["code", "crop"])["area_ha"].mean()
    # NBS writes "-" (no such event) for some cells where a district surely farmed the crop;
    # a yield only counts in a year with sown area, so such a gap cannot drag the median down.
    sown = rows[rows["year"].isin(YIELD_YEARS) & (rows["area_ha"] > 0)]
    expected_yield = sown.groupby(["code", "crop"])["yield_t_ha"].median()
    table = pd.concat(
        [area.rename("area_ha"), expected_yield.rename("expected_yield_t_ha")], axis=1
    ).reset_index()
    table["district"] = table["code"].map(nbs.DISTRICTS)
    table = table.join(scale_to_all_producers(district, national), on="crop")
    table = table.join(recent_prices(prices), on="crop")
    table["production_commercial_t"] = table["area_ha"] * table["expected_yield_t_ha"]
    table["value_commercial_usd"] = table["production_commercial_t"] * table["price_usd_t"]
    table["value_usd"] = table["value_commercial_usd"] * table["scale"]
    columns = [
        "district",
        "crop",
        "area_ha",
        "expected_yield_t_ha",
        "production_commercial_t",
        "scale",
        "price_usd_t",
        "value_commercial_usd",
        "value_usd",
    ]
    return table[columns].sort_values(["crop", "district"]).reset_index(drop=True)


def reconcile(table: pd.DataFrame, national: pd.DataFrame) -> pd.DataFrame:
    """Expected production in the exposure against what all producers actually harvested.

    The exposure should sit between the drought years and the best ones, near a typical year.
    """
    exposure = (table["production_commercial_t"] * table["scale"]).groupby(table["crop"]).sum()
    actual = national[(national["category"] == "all") & national["year"].isin(YIELD_YEARS)]
    by_year = actual.pivot(index="year", columns="crop", values="production_t")
    return pd.DataFrame(
        {
            "exposure_t": exposure,
            "median_year_t": by_year.median(),
            "mean_year_t": by_year.mean(),
            "min_year_t": by_year.min(),
            "max_year_t": by_year.max(),
        }
    )


def to_climada(table: pd.DataFrame, centroids: pd.DataFrame, crop: str) -> Any:
    """CLIMADA exposures for one crop: one point per district, at the hazard's centroid."""
    from climada.entity import Exposures

    rows = table[(table["crop"] == crop) & (table["value_usd"] > 0)]
    located = rows.join(centroids, on="district", how="left")
    if located[["lat", "lon"]].isna().any().any():
        missing = sorted(located.loc[located["lat"].isna(), "district"])
        raise ValueError(f"districts without a centroid: {missing}")
    frame = pd.DataFrame(
        {
            "latitude": located["lat"].to_numpy(),
            "longitude": located["lon"].to_numpy(),
            "value": located["value_usd"].to_numpy(dtype=np.float64),
            "impf_DR": IMPACT_FUNCTION_IDS[crop],
            "district": located["district"].to_numpy(),
        }
    )
    return Exposures(frame, crs="EPSG:4326", value_unit="USD")
