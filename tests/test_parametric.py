"""Payout rules, their fair pricing, and the basis-risk measures, on cases worked out by hand."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from drought_loss import config, hazard, parametric, vulnerability
from drought_loss.__main__ import run_parametric
from drought_loss.vulnerability import Curve


def test_binary_pays_its_fraction_from_the_trigger_on() -> None:
    rule = parametric.binary(0.6)
    np.testing.assert_allclose(rule.payout([0.0, 1.4, 1.5, 3.0]), [0.0, 0.0, 0.6, 0.6])


def test_ramp_rises_from_attachment_to_exhaustion_then_holds() -> None:
    rule = parametric.ramp(0.5)
    np.testing.assert_allclose(rule.payout([0.5, 1.0, 1.5, 2.0, 2.8]), [0.0, 0.0, 0.25, 0.5, 0.5])


def test_nothing_is_paid_without_a_drought() -> None:
    always = parametric.Product("always", lambda d: np.ones_like(d))
    np.testing.assert_allclose(always.payout([0.0, 0.0]), 0.0)


def test_expected_payout_of_the_binary_rule_is_fraction_times_trigger_probability() -> None:
    rule = parametric.binary(1.0)
    assert parametric.expected_payout_ratio(rule) == pytest.approx(stats.norm.cdf(-1.5), abs=1e-4)
    drier = parametric.expected_payout_ratio(rule, mean=-0.5)
    assert drier == pytest.approx(stats.norm.cdf(-1.0), abs=1e-4)


def test_fair_products_all_cost_the_crops_aal() -> None:
    for crop, curve in vulnerability.calibrated_curves().items():
        aal = vulnerability.average_annual_loss_ratio(curve)
        for product in parametric.fair_products(curve):
            assert parametric.expected_payout_ratio(product) == pytest.approx(aal, rel=1e-3), (
                crop,
                product.name,
            )


def test_the_curve_shaped_product_pays_the_damage_curve() -> None:
    curve = Curve(intercept=0.1, slope=0.2, curvature=-0.05, max_severity=2.5)
    product = parametric.curve_shaped(curve)
    np.testing.assert_allclose(product.payout([1.0, 2.0]), curve.loss([1.0, 2.0]))


def test_hedge_effectiveness_rewards_the_right_payout_and_punishes_the_wrong_one() -> None:
    loss = np.array([0.0, 10.0, 0.0, 30.0])
    assert parametric.hedge_effectiveness(loss, loss) == pytest.approx(1.0)
    assert parametric.hedge_effectiveness(loss, np.zeros(4)) == pytest.approx(0.0)
    assert parametric.hedge_effectiveness(loss, loss[::-1]) < 0  # pays in the wrong years
    assert parametric.hedge_effectiveness(loss, 3 * loss) < 0  # right years, far too much
    assert parametric.correlation(loss, 3 * loss) == pytest.approx(1.0)  # timing was perfect


def rows(severity: list[float], loss_ratio: list[float], years: list[int]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "district": ["a", "b"] * (len(years) // 2),
            "year": years,
            "severity": severity,
            "loss_ratio": loss_ratio,
            "value_usd": 100.0,
        }
    )


def test_basis_risk_counts_missed_losses_and_payouts_without_loss() -> None:
    table = rows(
        severity=[2.0, 0.0, 1.6, 1.8, 0.0, 0.0],
        loss_ratio=[0.5, 0.6, 0.05, 0.4, 0.0, 0.0],
        years=[2001, 2001, 2002, 2002, 2003, 2003],
    )
    metrics = parametric.basis_risk(parametric.with_payout(table, parametric.binary(0.5)))
    assert metrics["severe_losses"] == 3  # 0.5, 0.6 and 0.4
    assert metrics["severe_missed"] == pytest.approx(1 / 3)  # the 0.6 loss had no drought index
    assert metrics["payouts"] == 3
    assert metrics["paid_little_loss"] == pytest.approx(1 / 3)  # paid 0.5 on a 0.05 loss
    assert metrics["payout_over_loss"] == pytest.approx(150 / 155)
    assert metrics["loss_usd_per_year"] == pytest.approx(155 / 3)


def test_national_view_adds_districts_before_judging_the_hedge() -> None:
    # In each drought year the index points at the wrong district: useless locally, but the
    # national total is exactly right, which is what a holder of the whole country's risk needs.
    # (A third, calm year gives the national loss some variance to hedge.)
    table = rows(
        severity=[2.0, 0.0, 0.0, 2.0, 0.0, 0.0],
        loss_ratio=[0.0, 0.5, 0.5, 0.0, 0.0, 0.0],
        years=[2001, 2001, 2002, 2002, 2003, 2003],
    )
    metrics = parametric.basis_risk(parametric.with_payout(table, parametric.binary(0.5)))
    assert metrics["hedge_district"] < 0
    assert metrics["hedge_national"] == pytest.approx(1.0)


def test_a_loss_that_never_varies_has_no_hedge_effectiveness() -> None:
    assert np.isnan(parametric.hedge_effectiveness(np.full(3, 5.0), np.zeros(3)))


def test_backtest_rows_join_yields_index_and_value_by_district_and_year() -> None:
    anomalies = pd.DataFrame(
        {
            "code": ["17", "17", "57"],
            "crop": "maize",
            "year": [2007, 2008, 2007],
            "anomaly": [-0.6, 0.2, -0.1],
        }
    )
    spei = pd.DataFrame(
        {"Cahul": [-2.0, 0.5], "Leova": [-1.0, -0.2]}, index=pd.Index([2007, 2008], name="year")
    )
    values = pd.Series({"Cahul": 10.0, "Leova": 20.0})
    joined = parametric.backtest_rows(anomalies, spei, values, {"17": "Cahul", "57": "Leova"})
    cahul_2007 = joined[(joined.district == "Cahul") & (joined.year == 2007)].iloc[0]
    assert (cahul_2007.severity, cahul_2007.loss_ratio, cahul_2007.value_usd) == (2.0, 0.6, 10.0)
    cahul_2008 = joined[(joined.district == "Cahul") & (joined.year == 2008)].iloc[0]
    assert (cahul_2008.severity, cahul_2008.loss_ratio) == (0.0, 0.0)  # a gain is not a loss
    assert len(joined) == 3


def test_catalogue_payouts_add_districts_and_skip_uninsured_ones() -> None:
    severity = pd.DataFrame({"Cahul": [2.0, 0.0], "Bender": [2.0, 2.0]}, index=[1, 2])
    values = pd.Series({"Cahul": 100.0})  # Bender has no exposure
    annual = parametric.catalogue_payouts(severity, values, parametric.binary(0.5))
    assert list(annual) == [50.0, 0.0]


def test_a_private_index_cannot_send_results_into_this_repository(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="private data"):
        run_parametric(None, Path("stations_REAL.csv"), [], config.PROCESSED_DIR / "leak")
    (tmp_path / hazard.PROVENANCE_FILENAME).write_text(
        json.dumps({"spei_file": "x_REAL.csv", "first_year": 1, "last_year": 2}), encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="private data"):
        run_parametric(Path("cells"), None, [tmp_path], config.PROCESSED_DIR / "leak")
    assert not (config.PROCESSED_DIR / "leak").exists()
