"""The district layer gives one centroid per district (download checks: test_downloads.py)."""

import pandas as pd
import pytest

from drought_loss import boundaries, config, downloads


@pytest.fixture(scope="module")
def centroids() -> pd.DataFrame:
    if not downloads.is_verified(boundaries.DEFAULT_PATH, config.BOUNDARIES_SHA256):
        pytest.skip("district boundaries not downloaded; run: python -m drought_loss download")
    return boundaries.district_centroids()


@pytest.mark.raw
def test_thirty_seven_districts_including_both_sides_of_the_nistru(centroids: pd.DataFrame) -> None:
    assert len(centroids) == 37
    assert {"Chisinau", "Balti", "Gagauzia", "Bender", "Transnistria"} <= set(centroids.index)


@pytest.mark.raw
def test_every_centroid_lies_within_moldova(centroids: pd.DataFrame) -> None:
    assert centroids.lat.between(45.4, 48.5).all()
    assert centroids.lon.between(26.6, 30.2).all()
