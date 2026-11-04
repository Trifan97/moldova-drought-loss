"""CLIMADA does the arithmetic this project relies on, checked against a hand calculation.

These pin the behaviour of a dependency rather than test our code. If a CLIMADA upgrade
changes an answer, this file fails before any result quietly moves.
"""

from typing import Any

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray
from scipy import sparse

pytestmark = pytest.mark.climada

N_YEARS = 10
# Ten years at two sites, as drought severity D = max(0, -SPEI). Zero means no drought.
SEVERITY = np.array(
    [
        [2.0, 1.0],
        [1.0, 2.0],
        [0.5, 0.0],
        [0.0, 0.2],
        [1.5, 1.5],
        *([[0.0, 0.0]] * 5),
    ]
)
KNOTS = np.array([0.0, 0.5, 1.0, 2.0, 5.0])
LOSS_RATIO = np.array([0.0, 0.0, 0.2, 0.6, 0.6])
VALUES = np.array([100.0, 50.0])
LAT = np.array([47.0, 46.0])
LON = np.array([28.0, 28.5])


def hand_calculated_losses() -> NDArray[np.float64]:
    """Loss per year: interpolate each site's loss ratio, multiply by its value, sum."""
    ratios = np.interp(SEVERITY, KNOTS, LOSS_RATIO)
    return np.asarray((ratios * VALUES).sum(axis=1), dtype=np.float64)


@pytest.fixture(scope="module")
def impact() -> Any:
    from climada.engine import ImpactCalc
    from climada.entity import Exposures, ImpactFunc, ImpactFuncSet
    from climada.hazard import Centroids, Hazard

    hazard = Hazard(
        haz_type="DR",
        units="-SPEI",
        centroids=Centroids(lat=LAT, lon=LON, crs="EPSG:4326"),
        event_id=np.arange(1, N_YEARS + 1),
        event_name=[str(1960 + i) for i in range(N_YEARS)],
        date=np.full(N_YEARS, 719163),
        frequency=np.full(N_YEARS, 1 / N_YEARS),
        frequency_unit="1/year",
        intensity=sparse.csr_matrix(SEVERITY),
        fraction=sparse.csr_matrix((SEVERITY > 0).astype(float)),
    )
    exposures = Exposures(
        pd.DataFrame({"latitude": LAT, "longitude": LON, "value": VALUES, "impf_DR": 1}),
        crs="EPSG:4326",
    )
    function = ImpactFunc(
        haz_type="DR",
        id=1,
        intensity=KNOTS,
        mdd=LOSS_RATIO,
        paa=np.ones_like(KNOTS),
        intensity_unit="-SPEI",
    )
    calculator = ImpactCalc(exposures, ImpactFuncSet([function]), hazard)
    return calculator.impact(save_mat=True, assign_centroids=True)


def test_loss_per_event_matches_the_hand_calculation(impact: Any) -> None:
    np.testing.assert_allclose(impact.at_event, hand_calculated_losses())


def test_average_annual_loss_is_total_loss_over_record_length(impact: Any) -> None:
    assert impact.aai_agg == pytest.approx(hand_calculated_losses().sum() / N_YEARS)


def test_loss_per_site_sums_back_to_the_average_annual_loss(impact: Any) -> None:
    assert impact.eai_exp.sum() == pytest.approx(impact.aai_agg)


def test_impact_matrix_gives_loss_per_event_and_site(impact: Any) -> None:
    expected = np.interp(SEVERITY, KNOTS, LOSS_RATIO) * VALUES
    np.testing.assert_allclose(impact.imp_mat.toarray(), expected)


def test_exceedance_curve_goes_flat_past_the_record_length(impact: Any) -> None:
    # CLIMADA gives no warning here: asked for a 1-in-100 loss from ten years of data, it
    # returns the worst year. This is why our reporting must refuse return periods longer
    # than the record.
    curve = impact.calc_freq_curve(return_per=np.array([10, 20, 100]))
    worst_year = hand_calculated_losses().max()
    np.testing.assert_allclose(curve.impact, [worst_year, worst_year, worst_year])
