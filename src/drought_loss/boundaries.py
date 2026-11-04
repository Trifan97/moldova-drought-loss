"""Moldova's districts (geoBoundaries ADM1), downloaded once and pinned by SHA-256."""

from pathlib import Path

import geopandas as gpd
import pandas as pd

from drought_loss import config, downloads

DEFAULT_PATH = config.RAW_DIR / config.BOUNDARIES_FILENAME
# Centroids are taken in an equal-area projection (ETRS89 LAEA Europe), not in degrees.
EQUAL_AREA_CRS = 3035


def download_boundaries(
    dest: Path = DEFAULT_PATH,
    url: str = config.BOUNDARIES_URL,
    expected_sha256: str = config.BOUNDARIES_SHA256,
) -> Path:
    """Fetch the district layer unless a verified copy is already there."""
    return downloads.fetch_verified(url, dest, expected_sha256)


def district_centroids(path: Path = DEFAULT_PATH) -> pd.DataFrame:
    """One row per district (index: district), with its centroid's lat and lon."""
    if not downloads.is_verified(path, config.BOUNDARIES_SHA256):
        raise FileNotFoundError(
            f"{path} is missing or altered; run: python -m drought_loss download"
        )
    districts = gpd.read_file(path)
    centres = districts.to_crs(EQUAL_AREA_CRS).centroid.to_crs(4326)
    frame = pd.DataFrame(
        {"lat": centres.y.to_numpy(), "lon": centres.x.to_numpy()},
        index=pd.Index(districts["shapeName"], name="district"),
    )
    return frame.sort_index()
