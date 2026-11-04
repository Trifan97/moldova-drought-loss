# Moldova drought loss

A catastrophe-risk model of agricultural drought in Moldova, built on
[CLIMADA](https://github.com/CLIMADA-project/climada_python): hazard × exposure ×
vulnerability gives loss. It will report Average Annual Loss, a loss exceedance curve, loss
by district, and a parametric insurance trigger with its basis risk.

> **Status: scaffold only (step 1 of 9).** There is no model and there are no results yet.
> The repository holds the environment, the package skeleton and the tests described below.

## Data

The public results will use **synthetic drought data only**. Real station observations are
proprietary and are kept out of this repository. A test fails if a file that follows the
private naming convention (`*_REAL.*`), or anything in `data/` or `outputs/`, would be
committed.

## Quick start (Windows, PowerShell)

CLIMADA needs compiled GDAL, which pip cannot build on Windows, so the environment comes from
conda-forge through [micromamba](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html),
a single executable that changes nothing on your system. These commands use `F:\`; pick
another drive with at least 5 GB free if you need to, and set `$env:MAMBA_ROOT_PREFIX` and
`$env:DROUGHT_LOSS_ENV` to match, as `scripts\dev_env.ps1` explains.

```powershell
# Once: fetch micromamba (check it against the published .sha256 file in the same release)
New-Item -ItemType Directory -Force F:\micromamba | Out-Null
Invoke-WebRequest -UseBasicParsing -OutFile F:\micromamba\micromamba.exe `
    -Uri https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-win-64

# Once: build the environment from the exact tested versions (14 minutes on exFAT)
$env:MAMBA_ROOT_PREFIX = "F:\micromamba"
F:\micromamba\micromamba.exe create -y -p F:\envs\drought-loss -f environment.lock.txt

# In every new window:
. .\scripts\dev_env.ps1

# Once, after the first activation:
python -m pip install -e . --no-deps

pytest                       # everything
pytest -m "not climada"      # fast tests only, without loading CLIMADA
python -m drought_loss --version
```

`environment.yml` holds the loose requirements and `environment.lock.txt` the exact package
URLs and checksums that were tested (Windows 64-bit only). `--no-deps` stops pip from
re-resolving what conda installed.

If the repository is on exFAT, git will report "dubious ownership" because that file system
records no owner. Allow this folder once:

```bash
git config --global --add safe.directory "F:/Drought Loss Moldova CLIMADA"
```

## Repository layout

```
environment.yml         loose requirements
environment.lock.txt    exact tested versions (Windows 64-bit)
pyproject.toml          package metadata, pytest, ruff and mypy settings
climada.conf            keeps CLIMADA's data in data/climada, not in the home folder
src/drought_loss/       the package
tests/                  pytest suite (marker: `climada` loads CLIMADA)
scripts/dev_env.ps1     prepares a PowerShell window
data/, outputs/         downloaded inputs and generated outputs (git-ignored)
```

## Licence

Code: MIT (see `LICENSE`). Each data source will keep its own licence, listed here once it
is used.
