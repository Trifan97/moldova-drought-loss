"""The package installs and runs, with one version number."""

import subprocess
import sys
from importlib.metadata import version

import drought_loss


def test_version_comes_from_the_installed_metadata() -> None:
    # "unknown" here would mean the tests are importing a stray copy, not the installed package.
    assert drought_loss.__version__ == version("moldova-drought-loss")


def test_command_line_reports_the_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "drought_loss", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert drought_loss.__version__ in result.stdout
