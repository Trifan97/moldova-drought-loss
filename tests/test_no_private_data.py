"""Real station data must never reach this public repository.

A rule in .gitignore is not enough: `git add -f` bypasses it and a later edit can weaken it.
This test looks at what git would actually commit, so it fails before a bad commit exists.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from drought_loss.config import PRIVATE_NAME

REPO_ROOT = Path(__file__).resolve().parents[1]
# Everything in these folders is downloaded or generated, so only placeholders belong in git.
DATA_FOLDERS = ("data/", "outputs/")


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("git is not installed")
    # exFAT records no file owner, so git refuses the repository unless told it is safe.
    # Passing this per call changes nothing in your git configuration.
    safe = f"safe.directory={root.as_posix()}"
    return subprocess.run(
        [executable, "-c", safe, *args], cwd=root, capture_output=True, text=True, check=False
    )


def committable_files(root: Path) -> list[str]:
    """Tracked files, plus untracked ones that `git add .` would pick up."""
    result = git(root, "ls-files", "--cached", "--others", "--exclude-standard")
    if result.returncode != 0:
        pytest.skip(f"not a git checkout: {result.stderr.strip()}")
    return result.stdout.splitlines()


def violations(paths: list[str]) -> list[str]:
    private = [path for path in paths if PRIVATE_NAME.search(Path(path).name)]
    data = [
        path for path in paths if path.startswith(DATA_FOLDERS) and Path(path).name != ".gitkeep"
    ]
    return private + data


def test_nothing_private_can_be_committed() -> None:
    assert violations(committable_files(REPO_ROOT)) == []


@pytest.mark.parametrize(
    "name",
    ["master_dataset_v2_REAL.csv", "annual_timeseries_real.csv", "stations_REAL", "x_REAL_v2.csv"],
)
def test_gitignore_blocks_private_names(name: str) -> None:
    if git(REPO_ROOT, "rev-parse", "--git-dir").returncode != 0:
        pytest.skip("not a git checkout")
    assert git(REPO_ROOT, "check-ignore", "--no-index", name).returncode == 0


@pytest.mark.parametrize("name", ["surreal.py", "real_estate.csv", "unreal.txt", "REALLY.md"])
def test_ordinary_names_are_not_flagged(name: str) -> None:
    assert violations([name]) == []


def test_guard_catches_a_force_added_file(tmp_path: Path) -> None:
    # A guard that has never been seen to fail proves nothing, so make it fail on purpose.
    git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text("*_REAL.*\n", encoding="utf-8")
    (tmp_path / "stations_REAL.csv").write_text("station,spei\n", encoding="utf-8")
    assert violations(committable_files(tmp_path)) == []
    assert git(tmp_path, "add", "--force", "stations_REAL.csv").returncode == 0
    assert violations(committable_files(tmp_path)) == ["stations_REAL.csv"]


def test_guard_catches_data_outside_the_private_naming_convention() -> None:
    assert violations(["data/raw/stations.csv", "outputs/aal.csv"]) == [
        "data/raw/stations.csv",
        "outputs/aal.csv",
    ]
    assert violations(["data/raw/.gitkeep"]) == []
