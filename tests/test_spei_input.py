"""Station SPEI is checked on the way in, and private results cannot land in this repository."""

from pathlib import Path

import pandas as pd
import pytest

from drought_loss import config, spei_input, synthetic


def write(frame: pd.DataFrame, path: Path) -> Path:
    frame.to_csv(path, index=False)
    return path


def test_the_synthetic_csv_passes_and_extra_columns_are_dropped(tmp_path: Path) -> None:
    path = write(synthetic.generate(2, seed=1), tmp_path / "synthetic.csv")
    frame = spei_input.read_station_spei(path)
    assert list(frame.columns) == spei_input.COLUMNS
    assert len(frame) == 2 * 12 * len(config.STATIONS)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda f: f.drop(columns="spei_3"), "missing columns"),
        (lambda f: f.assign(station=f.station.replace("Balti", "Atlantis")), "not in config"),
        (lambda f: pd.concat([f, f.head(1)]), "more than one row"),
        (lambda f: f.assign(month=f.month.replace(12, 13)), "month must be"),
        (lambda f: f.assign(spei_3=f.spei_3.fillna(float("inf"))), "infinite"),
    ],
)
def test_malformed_tables_are_refused(tmp_path: Path, change: object, message: str) -> None:
    assert callable(change)
    path = write(change(synthetic.generate(2, seed=1)), tmp_path / "bad.csv")
    with pytest.raises(ValueError, match=message):
        spei_input.read_station_spei(path)


def test_missing_station_months_are_allowed(tmp_path: Path) -> None:
    frame = synthetic.generate(2, seed=1)
    path = write(frame.drop(index=frame.index[50]), tmp_path / "gappy.csv")
    assert len(spei_input.read_station_spei(path)) == len(frame) - 1


def test_private_results_cannot_be_written_inside_the_public_repository() -> None:
    with pytest.raises(SystemExit, match="private data"):
        spei_input.check_output_location(
            Path("master_dataset_v2_REAL.csv"), config.PROCESSED_DIR / "hazard"
        )


def test_private_results_may_go_outside_and_public_results_inside(tmp_path: Path) -> None:
    spei_input.check_output_location(Path("stations_REAL.csv"), tmp_path)
    spei_input.check_output_location(Path("synthetic_spei.csv"), config.PROCESSED_DIR)
