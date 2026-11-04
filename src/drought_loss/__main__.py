"""Command line: python -m drought_loss <stage>.

Stages arrive with the steps that implement them, so the help text never advertises something
that does not work yet.
"""

import argparse
from pathlib import Path

import numpy as np

from drought_loss import __version__, config, open_spei, synthetic


def write_synthetic(n_years: int, seed: int) -> None:
    frame = synthetic.generate(n_years, seed)
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = config.PROCESSED_DIR / f"synthetic_spei_{n_years}y_seed{seed}.csv"
    frame.to_csv(path, index=False)
    print(f"{len(frame):,} rows ({n_years} years x 12 months x {frame.station.nunique()} stations)")
    print(path)


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
    synth = stages.add_parser(
        "synthetic", help="write synthetic monthly SPEI for the 16 stations to data/processed"
    )
    synth.add_argument("--years", type=int, default=60, help="years to simulate (default 60)")
    synth.add_argument("--seed", type=int, default=config.SYNTHETIC_SEED)
    calibrate = stages.add_parser(
        "calibrate", help="re-fit the generator to the open SPEI cells and compare with config.py"
    )
    calibrate.add_argument("cells", type=Path, help="folder with the MD0*.xlsm cell workbooks")
    args = parser.parse_args(argv)

    if args.stage == "synthetic":
        write_synthetic(args.years, args.seed)
    else:
        recalibrate(args.cells)


if __name__ == "__main__":
    main()
