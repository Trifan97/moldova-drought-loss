"""The district layer is fetched once, verified by SHA-256, and gives one centroid per district."""

from pathlib import Path

import pandas as pd
import pytest

from drought_loss import boundaries, config


def test_a_download_with_the_wrong_checksum_is_refused_and_removed(tmp_path: Path) -> None:
    source = tmp_path / "source.geojson"
    source.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    dest = tmp_path / "raw" / "districts.geojson"
    with pytest.raises(ValueError, match="SHA-256"):
        boundaries.download_boundaries(dest, url=source.as_uri(), expected_sha256="0" * 64)
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".part").exists()


def test_a_verified_copy_is_not_downloaded_again(tmp_path: Path) -> None:
    dest = tmp_path / "districts.geojson"
    dest.write_text("already here", encoding="utf-8")
    url = (tmp_path / "does-not-exist").as_uri()
    assert boundaries.download_boundaries(dest, url, boundaries.sha256(dest)) == dest


@pytest.fixture(scope="module")
def centroids() -> pd.DataFrame:
    if not boundaries.is_verified(boundaries.DEFAULT_PATH, config.BOUNDARIES_SHA256):
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
