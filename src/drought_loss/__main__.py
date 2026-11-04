"""Command line: python -m drought_loss <stage>.

Stages arrive with the steps that implement them, so the help text never advertises something
that does not work yet.
"""

import argparse
from pathlib import Path

import numpy as np

from drought_loss import (
    __version__,
    boundaries,
    config,
    exposure,
    fao,
    hazard,
    nbs,
    open_spei,
    spei_input,
    synthetic,
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


def write_synthetic(n_years: int, seed: int) -> None:
    frame = synthetic.generate(n_years, seed)
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = config.PROCESSED_DIR / f"synthetic_spei_{n_years}y_seed{seed}.csv"
    frame.to_csv(path, index=False)
    print(f"{len(frame):,} rows ({n_years} years x 12 months x {frame.station.nunique()} stations)")
    print(path)


def build_hazard(spei_path: Path, out_dir: Path) -> None:
    spei_input.check_output_location(spei_path, out_dir)
    station_spei = spei_input.read_station_spei(spei_path)
    targets = boundaries.district_centroids()
    out_dir.mkdir(parents=True, exist_ok=True)
    n_stations, years = station_spei.station.nunique(), station_spei.year
    print(
        f"{spei_path.name}: {n_stations} stations, {years.min()}-{years.max()}, "
        f"{len(targets)} districts"
    )
    print(f"{'crop':<13}{'month':>6}{'gaps':>6}{'dry':>8}{'D>=1.5':>8}{'years half D>=1.5':>19}")
    for crop, month in hazard.CROP_MONTHS.items():
        severity = hazard.crop_severity(station_spei, targets, crop)
        severity.to_csv(out_dir / f"severity_{crop}.csv")
        hazard.to_climada(severity, targets, crop).write_hdf5(out_dir / f"hazard_{crop}.hdf5")
        # Station-years with no value in this month, each left out of that year's interpolation.
        gaps = n_stations * len(severity) - station_spei[station_spei.month == month].spei_3.count()
        summary = hazard.describe(severity)
        print(
            f"{crop:<13}{month:>6}{gaps:>6}{summary['share_dry']:>8.3f}"
            f"{summary['share_severe']:>8.3f}{summary['share_years_half_severe']:>19.3f}"
        )
    print(out_dir)


def recalibrate(cells_dir: Path) -> None:
    cells = open_spei.read_cells(cells_dir)
    fit = synthetic.calibrate(cells)
    print(f"cells: {fit.n_sites}, months {fit.first_month} to {fit.last_month}")
    print(f"range_km  fitted {fit.range_km:8.1f}   in config.py {config.SYNTHETIC_RANGE_KM:8.1f}")
    print(f"lag1      fitted {fit.lag1:8.4f}   in config.py {config.SYNTHETIC_LAG1:8.4f}")

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
        build_hazard(args.spei, args.out)
    else:
        recalibrate(args.cells)


if __name__ == "__main__":
    main()
