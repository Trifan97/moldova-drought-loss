"""Agricultural drought loss in Moldova, modelled with CLIMADA, plus a parametric trigger."""

from importlib.metadata import PackageNotFoundError, version

# Read the version from the installed package metadata, so pyproject.toml is the only
# place it is written down.
try:
    __version__ = version("moldova-drought-loss")
except PackageNotFoundError:
    __version__ = "unknown (not installed)"
