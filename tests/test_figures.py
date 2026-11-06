"""The figures stage: its data step, its public-only guard, and a full render on small inputs."""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from drought_loss import figures, hazard


def test_exceedance_points_give_the_kth_largest_a_return_period_of_n_over_k() -> None:
    periods, losses = figures.exceedance_points(pd.Series([3.0, 10.0, 0.0, 5.0]))
    np.testing.assert_allclose(losses, [10.0, 5.0, 3.0, 0.0])
    np.testing.assert_allclose(periods, [4.0, 2.0, 4 / 3, 1.0])


def write_provenance(folder: Path, spei_file: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / hazard.PROVENANCE_FILENAME).write_text(
        json.dumps({"spei_file": spei_file, "first_year": 1, "last_year": 2}), encoding="utf-8"
    )


def small_outputs(processed: Path, spei_file: str = "synthetic_spei.csv") -> Path:
    """Just enough of the pipeline's outputs, and a two-district map, to draw every figure."""
    rng = np.random.default_rng(0)
    districts = ["Cahul", "Leova"]
    for name, (hazard_dir, loss_dir) in figures.SOURCES.items():
        write_provenance(processed / hazard_dir, spei_file)
        n_years = 60 if name == "record" else 300
        rows = [
            (year, crop, district, float(rng.gamma(0.3, 1e6)))
            for year in range(1, n_years + 1)
            for crop in ("winter_wheat", "maize")
            for district in districts
        ]
        out = processed / loss_dir
        out.mkdir(parents=True)
        pd.DataFrame(rows, columns=["year", "crop", "district", "loss_usd"]).to_csv(
            out / "year_loss_table.csv", index=False
        )
        pd.DataFrame({"district": districts, "aal_usd": [1.5e6, 0.8e6]}).to_csv(
            out / "aal_by_district.csv", index=False
        )
    grid = np.round(np.arange(0.0, 3.0001, 0.1), 2)
    curves = [
        pd.DataFrame(
            {
                "crop": crop,
                "severity": grid,
                "loss_fitted": np.clip(grid - 1, 0, 1) * 0.3,
                "fitted_low_90": np.clip(grid - 1, 0, 1) * 0.2,
                "fitted_high_90": np.clip(grid - 1, 0, 1) * 0.4,
                "loss_anchored": np.clip(grid - 1, 0, 1) * 0.6,
            }
        )
        for crop in ("winter_wheat", "sunflower", "maize")
    ]
    pd.concat(curves).to_csv(processed / "vulnerability_open_cells.csv", index=False)
    boundaries = processed / "districts.geojson"
    gpd.GeoDataFrame(
        {"shapeName": [*districts, "Bender"]},
        geometry=[
            box(28.0, 45.9, 28.4, 46.3),
            box(28.0, 46.3, 28.4, 46.7),
            box(29.4, 46.8, 29.5, 46.9),
        ],
        crs="EPSG:4326",
    ).to_file(boundaries, driver="GeoJSON")
    return boundaries


def test_every_figure_is_drawn_in_both_themes(tmp_path: Path) -> None:
    boundaries = small_outputs(tmp_path / "processed")
    written = figures.render_all(tmp_path / "processed", boundaries, tmp_path / "img")
    names = sorted(path.name for path in written)
    assert names == sorted(
        f"{figure}-{theme}.png"
        for figure in ("exceedance", "district-map", "damage-curves")
        for theme in ("light", "dark")
    )
    for path in written:
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert path.stat().st_size > 10_000


def test_figures_refuse_outputs_that_came_from_private_data(tmp_path: Path) -> None:
    boundaries = small_outputs(tmp_path / "processed", spei_file="stations_REAL.csv")
    with pytest.raises(SystemExit, match="private data"):
        figures.render_all(tmp_path / "processed", boundaries, tmp_path / "img")
    assert not (tmp_path / "img").exists()
