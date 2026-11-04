# Moldova drought loss

A catastrophe-risk model of agricultural drought in Moldova, built on
[CLIMADA](https://github.com/CLIMADA-project/climada_python): hazard × exposure ×
vulnerability gives loss. It will report Average Annual Loss, a loss exceedance curve, loss
by district, and a parametric insurance trigger with its basis risk.

> **Status: step 2 of 9.** The synthetic drought generator works and is tested. There is no
> loss model and there are no results yet.

## Data

The public results will use **synthetic drought data only**. Real station observations are
proprietary and are kept out of this repository. A test fails if a file that follows the
private naming convention (`*_REAL.*`), or anything in `data/` or `outputs/`, would be
committed.

## Synthetic hazard

`python -m drought_loss synthetic` writes monthly SPEI-1 and SPEI-3 for Moldova's 16
meteorological stations. SPEI is standard normal in every calendar month by definition, so the
generator works in that space directly rather than simulating rainfall and standardising it:

- **Space:** monthly SPEI-1 is a Gaussian field with correlation exp(−distance / 605 km)
  between stations.
- **Time:** AR(1) with lag-1 autocorrelation 0.103.
- **SPEI-3:** the three-month sum of SPEI-1 divided by its exact standard deviation, so it is
  exactly N(0, 1) in every month.

**Calibration, from open data only.** The two parameters are fitted by
`python -m drought_loss calibrate <folder>` to 18 open 0.5° SPEI grid cells over Moldova
(January 1950 to September 2023), never to the station records. The range is fitted on
April–August, the months behind the June–August crop windows. Summer rain is patchier, so
fitting all months would overstate summer correlation (about 740 km).

Against the same cells, the generator reproduces:

| August SPEI-3 | Open cells (74 years) | Generator (20,000 years) |
|---|---|---|
| Mean correlation between cells | 0.804 | 0.810 |
| Years with half the cells at or below −1.5 | 0.081 (6 years) | 0.055 |

**What it leaves out:**

- **No climate trend.** In the open cells, mean August SPEI-3 moved from +0.33 (1951–1980) to
  −0.66 (2001–2023). A stationary generator averages over that shift, so it understates
  drought frequency in today's climate.
- **No joint extremes beyond the Gaussian.** The generator produces fewer nationwide drought
  years than observed (5.5 % against 8.1 %). With only 74 years the observed share has a 95 %
  interval of about 3 % to 17 %, so the data cannot settle the gap. Before 1990, joint
  extremes matched the Gaussian, which points to the trend rather than tail dependence.
- **Grid cells are smoother than stations.** The cells are interpolated, so they correlate
  more strongly than stations would. This pushes the national loss tail up, against the
  previous two points.
- **One persistence value for every month.** Observed lag-1 autocorrelation varies by month
  (from about −0.08 in October to 0.36 in March).
- **The exact CSIC product behind the cell files is not yet confirmed.** The parameters will
  be re-fitted if it turns out not to be open.

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

pytest                                  # everything (data tests skip without the cells)
pytest -m "not climada and not data"    # fast tests only
python -m drought_loss synthetic --years 60    # CSV into data/processed

# Re-fit the generator, and run the data tests, with the open SPEI cell workbooks:
python -m drought_loss calibrate "F:\Trifan PhD data\Database_SPEI_NUTS"
$env:DROUGHT_LOSS_OPEN_SPEI = "F:\Trifan PhD data\Database_SPEI_NUTS"
pytest -m data
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
  __main__.py           command line: python -m drought_loss synthetic | calibrate
  config.py             paths, station locations, the generator's fitted parameters
  synthetic.py          the synthetic SPEI generator and its calibration
  open_spei.py          reader for the open SPEI cell workbooks (calibration only)
tests/                  pytest suite (markers: `climada` loads CLIMADA, `data` needs the cells)
scripts/dev_env.ps1     prepares a PowerShell window
data/, outputs/         downloaded inputs and generated outputs (git-ignored)
```

## Licence

Code: MIT (see `LICENSE`). Each data source will keep its own licence, listed here once it
is used.
