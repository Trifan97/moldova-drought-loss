"""Exposure arithmetic on small tables built here, then checks on the real downloaded inputs."""

import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from drought_loss import boundaries, config, downloads, exposure, fao, nbs

# --- parsing -------------------------------------------------------------------------------


def write_px(path: Path, cells: list[tuple[list[str], str]]) -> Path:
    payload = {
        "columns": [
            {"code": "Raioane/Regiuni", "type": "d"},
            {"code": "Culturi agricole", "type": "d"},
            {"code": "Ani", "type": "t"},
            {"code": "Indicatori", "type": "d"},
            {"code": "Sown area...", "type": "c"},
        ],
        "comments": [],
        "data": [{"key": key, "values": [value]} for key, value in cells],
        "metadata": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_district_table_converts_quintals_to_tonnes_and_reads_nbs_markers(tmp_path: Path) -> None:
    cells = [
        (["17", "7", "2020", "0"], "1000"),  # area, ha
        (["17", "7", "2020", "1"], "35"),  # yield, quintals per ha
        (["17", "7", "2020", "2"], "35000"),  # harvest, quintals
        (["96", "2", "2016", "0"], "-"),  # "no such event": a true zero
        (["96", "2", "2016", "1"], ".."),  # unavailable: missing
        (["96", "2", "2016", "2"], "-"),
    ]
    table = nbs.read_district_table(write_px(tmp_path / "t.json", cells))
    assert len(table) == 2  # one row per district, crop and year present in the file
    cahul = table.set_index("code").loc["17"]
    assert (cahul.crop, cahul.year) == ("maize", 2020)
    assert cahul.area_ha == 1000 and cahul.yield_t_ha == 3.5 and cahul.harvest_t == 3500
    gagauzia = table.set_index("code").loc["96"]
    assert gagauzia.crop == "winter_wheat" and gagauzia.area_ha == 0
    assert np.isnan(gagauzia.yield_t_ha)


def test_faostat_extract_keeps_only_moldovas_annual_prices_for_the_three_crops(
    tmp_path: Path,
) -> None:
    header = "Area,Item,Element,Year,Months,Unit,Value,Flag\n"
    rows = [
        "Republic of Moldova,Maize (corn),Producer Price (USD/tonne),2024,Annual value,USD,167,A",
        "Republic of Moldova,Maize (corn),Producer Price (USD/tonne),2024,January,USD,150,A",
        "Republic of Moldova,Maize (corn),Producer Price (LCU/tonne),2024,Annual value,LCU,2900,A",
        "Republic of Moldova,Apples,Producer Price (USD/tonne),2024,Annual value,USD,300,A",
        "Romania,Maize (corn),Producer Price (USD/tonne),2024,Annual value,USD,190,A",
        "Republic of Moldova,Wheat,Producer Price (USD/tonne),2024,Annual value,USD,164,A",
    ]
    archive = tmp_path / "bulk.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("Prices_E_All_Data_(Normalized).csv", header + "\n".join(rows) + "\n")
    prices = fao.read_prices(fao.extract_moldova(archive, tmp_path / "moldova.csv"))
    kept = sorted(zip(prices.crop, prices.usd_per_t, strict=True))
    assert kept == [("maize", 167.0), ("winter_wheat", 164.0)]


# --- arithmetic ----------------------------------------------------------------------------


def district_rows(rows: list[tuple[str, str, int, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["code", "crop", "year", "area_ha", "yield_t_ha", "harvest_t"]
    )


def toy_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = []
    for year in exposure.YIELD_YEARS:
        dry = year in (2020, 2022, 2024)
        rows.append(("17", "maize", year, 100.0, 1.0 if dry else 4.0, 0.0))  # Cahul
    for year in exposure.YIELD_YEARS:
        rows.append(("0", "maize", year, 0.0, 0.0, 400.0))  # the table's national total
    district = district_rows(rows)
    national = pd.DataFrame(
        {
            "crop": "maize",
            "year": list(exposure.YIELD_YEARS),
            "category": "all",
            "production_t": 1000.0,
        }
    )
    prices = pd.DataFrame(
        {"crop": "maize", "year": range(2015, 2025), "usd_per_t": [100.0] * 5 + [200.0] * 5}
    )
    return district, national, prices


def test_value_is_area_times_median_yield_times_scale_times_price() -> None:
    table = exposure.build(*toy_inputs())
    row = table.iloc[0]
    assert row.district == "Cahul"
    assert row.expected_yield_t_ha == 4.0  # median: three drought years do not move it
    assert row.scale == pytest.approx(1000 / 400)
    assert row.price_usd_t == 200.0  # mean of the latest five years only
    assert row.value_commercial_usd == pytest.approx(100 * 4.0 * 200)
    assert row.value_usd == pytest.approx(100 * 4.0 * 200 * 2.5)


def test_a_year_without_sown_area_does_not_count_towards_expected_yield() -> None:
    # Two good years blanked as NBS "-". Left out, the median of the other eight stays 4.0;
    # counted as zero yields, they would pull it to (1.0 + 4.0) / 2 = 2.5.
    district, national, prices = toy_inputs()
    gap = (district.code == "17") & district.year.isin([2016, 2017])
    district.loc[gap, ["area_ha", "yield_t_ha"]] = 0.0
    row = exposure.build(district, national, prices).iloc[0]
    assert row.expected_yield_t_ha == 4.0


def test_only_named_districts_get_exposure_not_regional_totals() -> None:
    district, national, prices = toy_inputs()
    north = district[district.code == "17"].assign(code="MD011")
    table = exposure.build(pd.concat([district, north]), national, prices)
    assert list(table.district) == ["Cahul"]


def test_crosswalk_covers_35_districts_with_distinct_names() -> None:
    assert len(nbs.DISTRICTS) == 35
    assert len(set(nbs.DISTRICTS.values())) == 35
    assert not {nbs.WHOLE_COUNTRY, *nbs.REGIONS} & set(nbs.DISTRICTS)


@pytest.mark.climada
def test_climada_exposures_sit_on_the_district_centroids() -> None:
    table = exposure.build(*toy_inputs())
    centroids = pd.DataFrame({"lat": [45.9], "lon": [28.2]}, index=pd.Index(["Cahul"]))
    built = exposure.to_climada(table, centroids, "maize")
    built.check()
    assert built.value_unit == "USD"
    assert built.gdf["impf_DR"].tolist() == [exposure.IMPACT_FUNCTION_IDS["maize"]]
    assert built.gdf["value"].sum() == pytest.approx(table.value_usd.sum())
    with pytest.raises(ValueError, match="without a centroid"):
        exposure.to_climada(table, centroids.rename(index={"Cahul": "Leova"}), "maize")


# --- the real inputs -----------------------------------------------------------------------

INPUTS = [
    (nbs.DISTRICT_FILENAME, config.NBS_DISTRICT_SHA256),
    (nbs.NATIONAL_FILENAME, config.NBS_NATIONAL_SHA256),
    (fao.FILENAME, config.FAOSTAT_PRICES_SHA256),
    (config.BOUNDARIES_FILENAME, config.BOUNDARIES_SHA256),
]


@pytest.fixture(scope="module")
def real() -> dict[str, pd.DataFrame]:
    missing = [
        name for name, pin in INPUTS if not downloads.is_verified(config.RAW_DIR / name, pin)
    ]
    if missing:
        pytest.skip(f"not downloaded or altered: {missing}; run: python -m drought_loss download")
    district, national = nbs.read_district_table(), nbs.read_national_table()
    return {
        "district": district,
        "national": national,
        "table": exposure.build(district, national, fao.read_prices()),
        "centroids": boundaries.district_centroids(),
    }


@pytest.mark.raw
def test_every_district_and_crop_has_positive_exposure(real: dict[str, pd.DataFrame]) -> None:
    table = real["table"]
    assert len(table) == 35 * 3
    assert (table.value_usd > 0).all()


@pytest.mark.raw
def test_every_nbs_district_has_a_boundary_and_only_bender_and_transnistria_lack_data(
    real: dict[str, pd.DataFrame],
) -> None:
    names = set(real["centroids"].index)
    assert set(nbs.DISTRICTS.values()) <= names
    assert names - set(nbs.DISTRICTS.values()) == {"Bender", "Transnistria"}


@pytest.mark.raw
def test_districts_add_up_to_the_tables_national_row(real: dict[str, pd.DataFrame]) -> None:
    district = real["district"]
    named = district[district.code.isin(nbs.DISTRICTS)].groupby(["crop", "year"]).harvest_t.sum()
    whole = district[district.code == nbs.WHOLE_COUNTRY].set_index(["crop", "year"]).harvest_t
    ratio = (named / whole).drop(("winter_wheat", 2016))  # Gagauzia's wheat is "-" that year
    np.testing.assert_allclose(ratio, 1.0, atol=1e-3)


@pytest.mark.raw
def test_expected_production_lies_between_the_worst_and_best_recent_years(
    real: dict[str, pd.DataFrame],
) -> None:
    check = exposure.reconcile(real["table"], real["national"])
    assert (check.exposure_t > check.min_year_t).all()
    assert (check.exposure_t < check.max_year_t).all()
