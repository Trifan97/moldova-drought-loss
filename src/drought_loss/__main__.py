"""Command line: python -m drought_loss <stage>.

Stages arrive with the steps that implement them, so the help text never advertises something
that does not work yet.
"""

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from drought_loss import (
    __version__,
    boundaries,
    config,
    exposure,
    fao,
    hazard,
    loss,
    nbs,
    open_spei,
    spei_input,
    synthetic,
    vulnerability,
)


def download() -> None:
    # Each input is checked against its SHA-256 in config.py; verified copies are not refetched.
    print(boundaries.download_boundaries())
    for path in nbs.download_tables():
        print(path)
    print(fao.download_prices())


def build_exposure() -> None:
    national = nbs.read_national_table()
    table = exposure.build(nbs.read_district_table(), national, fao.read_prices())
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = config.PROCESSED_DIR / "exposure.csv"
    table.to_csv(path, index=False)
    by_crop = table.groupby("crop").agg(
        districts=("district", "count"),
        scale=("scale", "first"),
        price=("price_usd_t", "first"),
        commercial=("value_commercial_usd", "sum"),
        total=("value_usd", "sum"),
    )
    header = ["districts", "scale", "US$/t", "commercial", "all producers"]
    print(
        f"{'crop':<13}"
        + "".join(f"{h:>{w}}" for h, w in zip(header, [10, 7, 7, 14, 15], strict=True))
    )
    for crop, row in by_crop.iterrows():
        print(
            f"{crop:<13}{int(row.districts):>10}{row.scale:>7.3f}{row.price:>7.0f}"
            f"{row.commercial / 1e6:>12.1f} M{row.total / 1e6:>13.1f} M"
        )
    commercial, total = by_crop.commercial.sum() / 1e6, by_crop.total.sum() / 1e6
    print(f"{'total':<37}{commercial:>12.1f} M{total:>13.1f} M")
    print("\nExpected production against actual national harvests, 2016-2025 (thousand t):")
    print((exposure.reconcile(table, national) / 1000).round(0).to_string())
    print(path)


def fit_vulnerability(cells_dir: Path | None, stations: Path | None, out_dir: Path) -> None:
    if stations is not None:
        spei_input.check_output_location(stations, out_dir)
        site_spei, sites, label = spei_input.read_station_spei(stations), None, stations.stem
    else:
        assert cells_dir is not None
        site_spei, sites = open_spei.as_sites(open_spei.read_cells(cells_dir))
        label = "open_cells"
    centroids = boundaries.district_centroids()
    anomalies = vulnerability.yield_anomalies(nbs.read_district_table())
    pinned = vulnerability.calibrated_curves()
    report = [1.0, 1.5, 2.0, 2.5]
    grid = np.round(np.arange(0.0, 3.0001, 0.1), 2)
    tables = []
    for crop in hazard.CROP_MONTHS:
        spei = hazard.crop_spei(site_spei, centroids, crop, sites=sites)
        rows = vulnerability.panel(anomalies[anomalies["crop"] == crop], spei, nbs.DISTRICTS)
        curve = vulnerability.fit(rows)
        target = vulnerability.POTOPOVA_TABLE_6[crop]
        anchored = replace(curve, scale=vulnerability.anchor_scale(curve, target))
        scatter = vulnerability.residuals(rows, curve)
        # The interval describes the fitted shape; the anchor then sets its level.
        boot = vulnerability.bootstrap(rows, grid, 1000, config.SYNTHETIC_SEED)
        low, high = np.percentile(boot, [5, 95], axis=0)
        fitted, used = curve.loss(grid), anchored.loss(grid)
        tables.append(
            {
                "crop": crop,
                "severity": grid,
                "loss_fitted": fitted,
                "fitted_low_90": low,
                "fitted_high_90": high,
                "loss_anchored": used,
            }
        )
        years = rows["year"]
        print(
            f"\n{crop}: {len(rows)} district-years, {years.min()}-{years.max()}"
            f" | anomaly = {curve.intercept:+.4f} {curve.slope:+.4f} SPEI"
            f" {curve.curvature:+.4f} SPEI^2, used up to D = {curve.max_severity:.2f}"
        )
        print(f"  {'D':>5}  {'fitted (90% interval)':>24}  {'anchored':>9}")
        for d in report:
            i = int(round(d * 10))
            interval = f"{fitted[i]:.3f} ({low[i]:.3f}-{high[i]:.3f})"
            print(f"  {d:>5.1f}  {interval:>24}  {used[i]:>9.3f}")
        shared = scatter.within_year_correlation
        print(f"  scatter: sd {scatter.sd:.3f}, shared within a year {shared:.2f}")
        print(
            f"  mean loss when SPEI <= -1: fitted {vulnerability.mean_loss_given(curve):.3f},"
            f" anchor (Potopova et al. 2016) {target:.3f} -> scale {anchored.scale:.3f}"
        )
        print(
            "  AAL ratio under N(0,1):"
            f" fitted {vulnerability.average_annual_loss_ratio(curve):.4f},"
            f" anchored {vulnerability.average_annual_loss_ratio(anchored):.4f}"
        )
        if stations is None:
            print(f"  in config.py: {pinned[crop]}")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"vulnerability_{label}.csv"
    pd.concat([pd.DataFrame(t) for t in tables]).to_csv(path, index=False)
    print(path)


def write_synthetic(n_years: int, seed: int) -> None:
    frame = synthetic.generate(n_years, seed)
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = config.PROCESSED_DIR / f"synthetic_spei_{n_years}y_seed{seed}.csv"
    frame.to_csv(path, index=False)
    print(f"{len(frame):,} rows ({n_years} years x 12 months x {frame.station.nunique()} stations)")
    print(path)


def build_hazard(spei_path: Path, out_dir: Path, climate: str = "stationary") -> None:
    spei_input.check_output_location(spei_path, out_dir)
    shifts = (
        dict(config.RECENT_CLIMATE_SHIFT)
        if climate == "recent"
        else {crop: 0.0 for crop in hazard.CROP_MONTHS}
    )
    station_spei = spei_input.read_station_spei(spei_path)
    targets = boundaries.district_centroids()
    out_dir.mkdir(parents=True, exist_ok=True)
    n_stations, years = station_spei.station.nunique(), station_spei.year
    print(
        f"{spei_path.name}: {n_stations} stations, {years.min()}-{years.max()}, "
        f"{len(targets)} districts, {climate} climate"
    )
    if climate == "recent":
        print("SPEI-3 shift per crop:", ", ".join(f"{c} {s:+.3f}" for c, s in shifts.items()))
    print(f"{'crop':<13}{'month':>6}{'gaps':>6}{'dry':>8}{'D>=1.5':>8}{'years half D>=1.5':>19}")
    for crop, month in hazard.CROP_MONTHS.items():
        severity = hazard.crop_severity(station_spei, targets, crop, shift=shifts[crop])
        severity.to_csv(out_dir / f"severity_{crop}.csv")
        hazard.to_climada(severity, targets, crop).write_hdf5(out_dir / f"hazard_{crop}.hdf5")
        # Station-years with no value in this month, each left out of that year's interpolation.
        gaps = n_stations * len(severity) - station_spei[station_spei.month == month].spei_3.count()
        summary = hazard.describe(severity)
        print(
            f"{crop:<13}{month:>6}{gaps:>6}{summary['share_dry']:>8.3f}"
            f"{summary['share_severe']:>8.3f}{summary['share_years_half_severe']:>19.3f}"
        )
    hazard.write_provenance(out_dir, spei_path, severity.index, climate, shifts)
    print(out_dir)


def compute_loss(hazard_dir: Path, out_dir: Path) -> None:
    provenance = hazard.read_provenance(hazard_dir)
    # Checked before CLIMADA loads, so a refused run stops at once.
    spei_input.check_output_location(Path(provenance["spei_file"]), out_dir)
    from climada.hazard import Hazard

    exposure_table = exposure.build(
        nbs.read_district_table(), nbs.read_national_table(), fao.read_prices()
    )
    centroids = boundaries.district_centroids()
    functions = vulnerability.impact_functions(vulnerability.calibrated_curves())
    impacts, exposures = {}, {}
    for crop in hazard.CROP_MONTHS:
        exposures[crop] = exposure.to_climada(exposure_table, centroids, crop)
        crop_hazard = Hazard.from_hdf5(hazard_dir / f"hazard_{crop}.hdf5")
        impacts[crop] = loss.crop_impact(crop_hazard, exposures[crop], functions)
    table = loss.year_loss_table(impacts, exposures)
    annual = loss.annual_losses(table)
    commercial = loss.commercial_annual_losses(table, exposure_table)
    n_years = len(annual)
    periods = loss.reportable(loss.RETURN_PERIODS, n_years)

    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_dir / "year_loss_table.csv", index=False)
    districts = loss.by_district(table, exposure_table)
    districts.to_csv(out_dir / "aal_by_district.csv")

    m = 1e6
    print(
        f"{provenance['spei_file']}: {provenance['first_year']}-{provenance['last_year']}"
        f" ({n_years} years), {provenance.get('climate', 'stationary')} climate"
    )
    aal = loss.average_annual_loss(table)
    value = exposure_table.groupby("crop")["value_usd"].sum()
    share = loss.commercial_share(exposure_table)
    print(f"\n{'AAL, US$ M':<14}{'all producers':>14}{'commercial':>12}{'loss ratio':>12}")
    for crop in hazard.CROP_MONTHS:
        print(
            f"{crop:<14}{aal[crop] / m:>14.1f}{aal[crop] * share[crop] / m:>12.1f}"
            f"{aal[crop] / value[crop]:>12.2%}"
        )
    print(
        f"{'total':<14}{aal.sum() / m:>14.1f}{commercial.mean() / m:>12.1f}"
        f"{aal.sum() / value.sum():>12.2%}"
    )

    curve = loss.exceedance(annual, periods)
    curve_commercial = loss.exceedance(commercial, periods)
    by_crop = table.groupby(["crop", "year"])["loss_usd"].sum()
    crop_sum = sum(loss.exceedance(by_crop.loc[crop], periods) for crop in hazard.CROP_MONTHS)
    print(f"\n{'Return period':<14}{'all producers':>14}{'commercial':>12}{'sum of crops':>14}")
    for t in periods:
        row = [curve[t] / m, curve_commercial[t] / m, crop_sum[t] / m]
        print(f"{t:>8} yr    {row[0]:>14.1f}{row[1]:>12.1f}{row[2]:>14.1f}")
    longer = [t for t in loss.RETURN_PERIODS if t > n_years]
    if longer:
        print(f"  (not reported: {longer} years, longer than the {n_years}-year record)")
    if n_years <= 1000:
        spread = loss.bootstrap(annual, periods, 1000, 0).quantile([0.05, 0.95]) / m
        print("90% interval from resampling the record's years:")
        print(f"  AAL {spread['aal'].iloc[0]:.1f}-{spread['aal'].iloc[1]:.1f}")
        for t in periods:
            print(f"  {t:>4} yr {spread[t].iloc[0]:.1f}-{spread[t].iloc[1]:.1f}")

    worst = annual.sort_values(ascending=False).head(5)
    print("\nWorst years (US$ M):", ", ".join(f"{y}: {v / m:.0f}" for y, v in worst.items()))
    print("\nDistricts with the largest AAL:")
    print(
        (districts.head(8)[["aal_usd", "exposure_usd"]] / m)
        .round(1)
        .join(districts.head(8)[["loss_ratio", "share_of_aal"]].round(3))
        .to_string()
    )
    print(out_dir)


def recalibrate(cells_dir: Path) -> None:
    cells = open_spei.read_cells(cells_dir)
    fit = synthetic.calibrate(cells)
    print(f"cells: {fit.n_sites}, months {fit.first_month} to {fit.last_month}")
    print(f"range_km  fitted {fit.range_km:8.1f}   in config.py {config.SYNTHETIC_RANGE_KM:8.1f}")
    print(f"lag1      fitted {fit.lag1:8.4f}   in config.py {config.SYNTHETIC_LAG1:8.4f}")
    first = config.RECENT_CLIMATE_FIRST_YEAR
    for crop, month in hazard.CROP_MONTHS.items():
        shift = synthetic.recent_climate_shift(cells, month, first)
        pinned = config.RECENT_CLIMATE_SHIFT[crop]
        print(f"shift since {first}, {crop:<12} fitted {shift:+8.4f}   in config.py {pinned:+8.4f}")

    # The check that matters for the loss tail: how often is most of the country dry at once?
    # Simulate at the cells themselves (not the stations), so like is compared with like.
    observed = synthetic.by_site(cells, "spei_3").xs(8, level="month")
    coords = np.array(observed.columns.tolist(), dtype=np.float64)
    corr = synthetic.correlation_matrix(coords[:, 0], coords[:, 1], config.SYNTHETIC_RANGE_KM)
    rng = np.random.default_rng(config.SYNTHETIC_SEED)
    n_years = 20_000
    spei1 = synthetic.simulate_spei1(n_years * 12, corr, config.SYNTHETIC_LAG1, rng)
    simulated_aug = synthetic.accumulate(spei1, 3, config.SYNTHETIC_LAG1)[7::12]
    upper = np.triu_indices(len(coords), 1)
    print(f"August SPEI-3 at the same cells, observed ({len(observed)} years) vs generator:")
    observed_share = synthetic.joint_drought_share(observed)
    simulated_share = synthetic.joint_drought_share(simulated_aug)
    print(
        f"  years with half the cells at or below -1.5: {observed_share:.3f}"
        f" vs {simulated_share:.3f}"
    )
    print(
        f"  mean correlation between cells: {observed.corr().to_numpy()[upper].mean():.3f}"
        f" vs {np.corrcoef(simulated_aug.T)[upper].mean():.3f}"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m drought_loss")
    parser.add_argument("--version", action="version", version=f"drought_loss {__version__}")
    stages = parser.add_subparsers(dest="stage", required=True)
    stages.add_parser(
        "download", help="fetch the boundaries, NBS crop tables and FAOSTAT prices into data/raw"
    )
    stages.add_parser("exposure", help="crop value per district, into data/processed")
    synth = stages.add_parser(
        "synthetic", help="write synthetic monthly SPEI for the 16 stations to data/processed"
    )
    synth.add_argument("--years", type=int, default=60, help="years to simulate (default 60)")
    synth.add_argument("--seed", type=int, default=config.SYNTHETIC_SEED)
    build = stages.add_parser(
        "hazard", help="crop-season drought hazard per district, from a station SPEI CSV"
    )
    build.add_argument("spei", type=Path, help="CSV with station, year, month, spei_3")
    build.add_argument(
        "--out", type=Path, default=config.PROCESSED_DIR / "hazard", help="output folder"
    )
    build.add_argument(
        "--climate",
        choices=["stationary", "recent"],
        default="stationary",
        help="recent: shift each crop month's SPEI-3 to its 2001-2023 mean (a sensitivity)",
    )
    loss_stage = stages.add_parser(
        "loss", help="AAL, exceedance curve and loss by district, from a hazard folder"
    )
    loss_stage.add_argument("hazard", type=Path, help="folder written by the hazard stage")
    loss_stage.add_argument(
        "--out", type=Path, default=config.PROCESSED_DIR / "loss", help="output folder"
    )
    vuln = stages.add_parser(
        "vulnerability", help="fit the impact functions to NBS district yields against SPEI"
    )
    source = vuln.add_mutually_exclusive_group(required=True)
    source.add_argument("--cells", type=Path, help="folder with the open MD0*.xlsm cells (public)")
    source.add_argument("--stations", type=Path, help="station SPEI CSV (private check)")
    vuln.add_argument("--out", type=Path, default=config.PROCESSED_DIR, help="output folder")
    calibrate = stages.add_parser(
        "calibrate", help="re-fit the generator to the open SPEI cells and compare with config.py"
    )
    calibrate.add_argument("cells", type=Path, help="folder with the MD0*.xlsm cell workbooks")
    args = parser.parse_args(argv)

    if args.stage == "download":
        download()
    elif args.stage == "exposure":
        build_exposure()
    elif args.stage == "synthetic":
        write_synthetic(args.years, args.seed)
    elif args.stage == "hazard":
        build_hazard(args.spei, args.out, args.climate)
    elif args.stage == "loss":
        compute_loss(args.hazard, args.out)
    elif args.stage == "vulnerability":
        fit_vulnerability(args.cells, args.stations, args.out)
    else:
        recalibrate(args.cells)


if __name__ == "__main__":
    main()
