"""A parametric drought cover: payout rules on the SPEI index, their price, and their basis risk.

A parametric cover pays on an index, here SPEI-3 in each crop's window at each district,
not on a loss adjuster's assessment. That makes it fast and cheap to run, and imperfect:
the farmer's loss and the index can disagree. That disagreement is basis risk.

Three payout rules are compared, each scaled so that its expected payout under the stationary
hazard equals the model's AAL for the crop, so they cost the same:

- binary: a fixed share of the insured value when SPEI-3 <= -1.5;
- ramp: from nothing at SPEI-3 = -1.0 to a full limit at -2.0;
- curve: the model's own damage curve, the most loss-like an index payout can be.

Basis risk is measured against what actually happened: payouts on the index for each district
and year, set against the yield shortfall NBS recorded. Comparing payouts with modelled losses
from the same index would show almost no basis risk, by construction.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike
from scipy import stats

from drought_loss.synthetic import FloatArray
from drought_loss.vulnerability import Curve, average_annual_loss_ratio, normal_grid

TRIGGER = 1.5  # binary: pays when severity D = -SPEI-3 is at least this
ATTACH, EXHAUST = 1.0, 2.0  # ramp: starts paying at D = 1.0, pays the full limit from D = 2.0
# Basis-risk thresholds on the recorded loss (yield shortfall below trend, share of expected).
SEVERE_LOSS = 0.30
LITTLE_LOSS = 0.10


@dataclass(frozen=True)
class Product:
    """A payout rule: share of the insured value paid at severity D (D = 0 pays nothing)."""

    name: str
    rule: Callable[[FloatArray], FloatArray]

    def payout(self, severity: ArrayLike) -> FloatArray:
        d = np.asarray(severity, dtype=np.float64)
        return np.where(d > 0, self.rule(d), 0.0)


def binary(fraction: float, trigger: float = TRIGGER) -> Product:
    return Product("binary", lambda d: np.where(d >= trigger, fraction, 0.0))


def ramp(limit: float, attach: float = ATTACH, exhaust: float = EXHAUST) -> Product:
    return Product("ramp", lambda d: limit * np.clip((d - attach) / (exhaust - attach), 0.0, 1.0))


def curve_shaped(curve: Curve) -> Product:
    return Product("curve", curve.loss)


def expected_payout_ratio(product: Product, mean: float = 0.0) -> float:
    """Expected payout per year, as a share of the insured value, with SPEI-3 ~ N(mean, 1)."""
    z, pdf = normal_grid(mean)
    return float(np.trapezoid(product.payout(np.maximum(0.0, -z)) * pdf, z))


def fair_products(curve: Curve) -> list[Product]:
    """The three rules, each scaled so its expected payout equals the curve's AAL ratio."""
    aal = average_annual_loss_ratio(curve)
    fraction = aal / float(stats.norm.cdf(-TRIGGER))
    limit = aal / expected_payout_ratio(ramp(1.0))
    return [binary(fraction), ramp(limit), curve_shaped(curve)]


def backtest_rows(
    anomalies: pd.DataFrame, spei: pd.DataFrame, values: pd.Series, codes_to_names: dict[str, str]
) -> pd.DataFrame:
    """One crop's district-years with recorded loss, index severity and insured value.

    `anomalies`: code, year, anomaly (yield over trend, minus 1); `spei`: years x district
    names; `values`: insured value per district name.
    """
    long = spei.stack().rename("spei").reset_index()
    long.columns = ["year", "district", "spei"]
    named = anomalies.assign(district=anomalies["code"].map(codes_to_names))
    rows = named.merge(long, on=["district", "year"], how="inner").dropna(
        subset=["spei", "anomaly"]
    )
    rows["severity"] = np.maximum(0.0, -rows["spei"])
    rows["loss_ratio"] = np.clip(-rows["anomaly"], 0.0, 1.0)
    rows["value_usd"] = rows["district"].map(values)
    return rows[["district", "year", "severity", "loss_ratio", "value_usd"]].reset_index(drop=True)


def hedge_effectiveness(loss: FloatArray, payout: FloatArray) -> float:
    """Share of the loss's variance the payout removes: 1 - Var(loss - payout) / Var(loss).

    1 is a perfect hedge, 0 no better than no cover, below 0 worse than none. It depends on
    both timing and size: a payout in the right years but twice too large still adds variance.
    The best any rescaling of the same payout can reach is the squared correlation.
    """
    if np.var(loss) == 0:
        return float("nan")  # nothing to hedge: the loss never varies
    return float(1.0 - np.var(loss - payout) / np.var(loss))


def correlation(loss: FloatArray, payout: FloatArray) -> float:
    return float(np.corrcoef(loss, payout)[0, 1]) if np.std(payout) > 0 else float("nan")


def with_payout(rows: pd.DataFrame, product: Product) -> pd.DataFrame:
    return rows.assign(payout_ratio=product.payout(rows["severity"].to_numpy()))


def basis_risk(rows: pd.DataFrame) -> dict[str, float]:
    """How payouts (column payout_ratio) would have matched the recorded losses.

    Per district-year, and nationally: summed over districts (and crops, if several are in
    `rows`) for each year, which is how a government holding the cover would see it.
    """
    paid_ratio = rows["payout_ratio"].to_numpy()
    loss = rows["loss_ratio"].to_numpy() * rows["value_usd"].to_numpy()
    payout = paid_ratio * rows["value_usd"].to_numpy()
    severe = rows["loss_ratio"].to_numpy() >= SEVERE_LOSS
    paid = paid_ratio > 0
    national = (
        pd.DataFrame({"year": rows["year"], "loss": loss, "payout": payout})
        .groupby("year")[["loss", "payout"]]
        .sum()
    )
    national_loss, national_payout = national["loss"].to_numpy(), national["payout"].to_numpy()
    return {
        "severe_losses": float(severe.sum()),
        "severe_missed": float(np.mean(~paid[severe])) if severe.any() else float("nan"),
        "payouts": float(paid.sum()),
        "paid_little_loss": float(np.mean(rows["loss_ratio"].to_numpy()[paid] < LITTLE_LOSS))
        if paid.any()
        else float("nan"),
        "payout_over_loss": float(payout.sum() / loss.sum()),
        "correlation_district": correlation(loss, payout),
        "hedge_district": hedge_effectiveness(loss, payout),
        "correlation_national": correlation(national_loss, national_payout),
        "hedge_national": hedge_effectiveness(national_loss, national_payout),
        "loss_usd_per_year": float(national_loss.mean()),
        "payout_usd_per_year": float(national_payout.mean()),
    }


def catalogue_payouts(severity: pd.DataFrame, values: pd.Series, product: Product) -> pd.Series:
    """Annual payout in US$ over a hazard catalogue (years x districts severity)."""
    insured = values.reindex(severity.columns).fillna(0.0).to_numpy()
    return pd.Series(
        (product.payout(severity.to_numpy()) * insured).sum(axis=1), index=severity.index
    )
