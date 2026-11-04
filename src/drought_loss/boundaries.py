"""Moldova's districts (geoBoundaries ADM1), downloaded once and pinned by SHA-256."""

import hashlib
import shutil
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd

from drought_loss import config

DEFAULT_PATH = config.RAW_DIR / config.BOUNDARIES_FILENAME
# Centroids are taken in an equal-area projection (ETRS89 LAEA Europe), not in degrees.
EQUAL_AREA_CRS = 3035


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def is_verified(path: Path, expected: str) -> bool:
    return path.exists() and sha256(path) == expected


def download_boundaries(
    dest: Path = DEFAULT_PATH,
    url: str = config.BOUNDARIES_URL,
    expected_sha256: str = config.BOUNDARIES_SHA256,
) -> Path:
    """Fetch the district layer unless a verified copy is already there."""
    if is_verified(dest, expected_sha256):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Download beside the target and move it into place only once verified, so an interrupted
    # or altered download never sits where the pipeline will read it.
    partial = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    if not is_verified(partial, expected_sha256):
        partial.unlink()
        raise ValueError(f"SHA-256 of {url} does not match config.BOUNDARIES_SHA256")
    partial.replace(dest)
    return dest


def district_centroids(path: Path = DEFAULT_PATH) -> pd.DataFrame:
    """One row per district (index: district), with its centroid's lat and lon."""
    if not is_verified(path, config.BOUNDARIES_SHA256):
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
