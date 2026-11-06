# Moldova drought loss

A catastrophe-risk model of agricultural drought in Moldova, built on
[CLIMADA](https://github.com/CLIMADA-project/climada_python): hazard × exposure ×
vulnerability gives loss. It will report Average Annual Loss, a loss exceedance curve, loss
by district, and a parametric insurance trigger with its basis risk.

> **Status: step 7 of 9.** Hazard, exposure, impact functions, the loss calculation and the
> parametric cover work and are tested. Loss results come from **synthetic** drought data; the
> basis-risk backtest uses recorded NBS yields and open SPEI. The write-up and verdict are next.

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
`python -m drought_loss calibrate <folder>` to 18 cells of CSIC's Global 0.5° SPEI database
over Moldova, never to the station records. The cells are per-location exports from
[spei.csic.es](https://spei.csic.es/database.html), downloaded in November 2023 and covering
January 1950 to September 2023. The range is fitted on April–August, the months behind the
June–August crop windows. Summer rain is patchier, so fitting all months would overstate
summer correlation (about 740 km).

Against the same cells, the generator reproduces:

| August SPEI-3 | Open cells (74 years) | Generator (20,000 years) |
|---|---|---|
| Mean correlation between cells | 0.804 | 0.810 |
| Years with half the cells at or below −1.5 | 0.081 (6 years) | 0.055 |

**What it leaves out:**

- **No climate trend.** In the open cells, mean August SPEI-3 moved from +0.33 (1951–1980) to
  −0.66 (2001–2023). A stationary generator averages over that shift, so it understates
  drought frequency in today's climate; the current-climate sensitivity under Loss measures how
  much.
- **No joint extremes beyond the Gaussian.** The generator produces fewer nationwide drought
  years than observed (5.5 % against 8.1 %). With only 74 years the observed share has a 95 %
  interval of about 3 % to 17 %, so the data cannot settle the gap. Before 1990, joint
  extremes matched the Gaussian, which points to the trend rather than tail dependence.
- **Grid cells are smoother than stations.** The cells are interpolated, so they correlate
  more strongly than stations would. This pushes the national loss tail up, against the
  previous two points.
- **One persistence value for every month.** Observed lag-1 autocorrelation varies by month
  (from about −0.08 in October to 0.36 in March).

## Crop-season hazard

`python -m drought_loss hazard <station SPEI CSV>` turns monthly station SPEI into one CLIMADA
hazard per crop, with one event per year at each of Moldova's 37 districts:

- **Crop window.** Each crop's SPEI-3 is read at the end of its drought-sensitive period in
  Moldova (Potopová et al. 2016): June for winter wheat (anthesis to grain fill), July for
  sunflower (flowering to grain fill), August for maize (silking to milk).
- **Severity.** D = max(0, −SPEI-3), so zero means no drought. CLIMADA stores intensity as a
  sparse matrix in which zero means "no hazard", and its exceedance tools assume larger is
  worse.
- **From stations to districts.** SPEI at each district centroid is the simple-kriging
  prediction from the stations, under the generator's correlation model, divided by the
  prediction's standard deviation. Without that division, averaging correlated N(0, 1) values
  shrinks the extremes, and with a convex loss curve that understates loss. A station missing
  in a year is left out of that year's prediction only.
- **Districts.** The 37 units of geoBoundaries ADM1, including Bender and Transnistria. Their
  centroids are taken in an equal-area projection (EPSG:3035).
- **Probability.** Each year in the record is one event with probability 1 / (number of
  years). That treats the record as a sample of one unchanging climate (see the trend above).

On the 60-year synthetic record (seed 42), the share of district-years in each class:

| Crop (month) | D > 0 | D ≥ 1.5 | Years with half the districts at D ≥ 1.5 |
|---|---|---|---|
| Winter wheat (June) | 0.641 | 0.064 | 0.033 (2 years) |
| Sunflower (July) | 0.602 | 0.096 | 0.117 (7 years) |
| Maize (August) | 0.565 | 0.058 | 0.050 (3 years) |

Under N(0, 1) the first two columns would be 0.5 and 0.067. With districts this strongly
correlated, 60 years behave like far fewer independent draws, so a single 60-year sample
wanders that much. That is why the loss results will also use a long synthetic catalogue.

**What it leaves out:** each district gets the value at one point, its centroid, not an
average over its farmland; and the same open-data correlation model is used to interpolate
the private station data.

## Exposure

`python -m drought_loss exposure` values each crop's expected harvest in each district:

value = sown area × expected yield × scale-up to all producers × producer price

| Factor | Source and rule | Why |
|---|---|---|
| Sown area | NBS, mean of 2021–2025 | Today's farms, held fixed against every hazard year (an "as-if" exposure). |
| Expected yield | NBS, median of 2016–2025, only years with sown area | Loss is measured against typical yield; a median is not dragged down by the drought years this model is about. |
| Scale-up | NBS national production by all producers ÷ the district table's national total, 2016–2025 | The district table covers enterprises and farms of 10 ha or more only. |
| Price | FAOSTAT producer price, mean of 2020–2024, nominal US$ | Smooths the 2021–2022 price spike without ignoring it. |

| Crop | Scale-up | US$/t | Commercial farms | All producers |
|---|---|---|---|---|
| Maize | 2.05 | 181 | $145 M | $298 M |
| Sunflower | 1.13 | 464 | $343 M | $385 M |
| Winter wheat | 1.11 | 179 | $212 M | $234 M |
| **Total** | | | **$700 M** | **$918 M** |

Households grow a third of Moldova's maize but almost no sunflower or wheat, so the scale-up
matters mainly for maize. Both values are kept, because insurance mostly reaches commercial
farms while a national disaster-risk view counts every producer.

**Checks.** The 35 districts add up to the NBS table's national row (to 0.1 %, except winter
wheat in 2016, when Gagauzia's entry is "-"). Expected production lies between the worst and
best years of 2016–2025, about 8–12 % above the average year: drought years pull an average
down, which a median ignores. The impact functions measure yield loss against each district's
Theil–Sen trend, the median-based counterpart of that baseline, so exposure and damage agree.

**What it leaves out:**

- **Smallholders are placed like large farms.** The scale-up assumes household maize is spread
  across districts in the same way as commercial maize.
- **No left bank, no Bender.** NBS excludes them, so the geoBoundaries units "Transnistria" and
  "Bender" carry no exposure, although the hazard covers them.
- **Prices do not react to drought.** A national harvest failure can raise local prices and
  soften the loss in money; the model holds prices fixed. Loss in money scales one for one
  with the price assumption.
- **Three crops only.** Barley, soy, sugar beet, vegetables, orchards and vineyards are not in
  the model.

## Impact functions

`python -m drought_loss vulnerability --cells <folder>` fits one curve per crop on public data:
NBS yields for 35 districts against SPEI-3 in the crop's window, 2007–2023 (17 years), with the
SPEI taken from the open CSIC cells and interpolated to district centroids as in the hazard.

- **Yield anomaly.** Each district's yield over its own Theil–Sen trend, minus 1. Yields rose
  3–4 % a year over 2007–2025, so a fixed baseline would count old technology as drought.
  Theil–Sen uses the median of pairwise slopes, so drought years do not drag the trend down.
- **Curve.** anomaly = a + b·SPEI + c·SPEI², the second-order polynomial Potopová et al. (2016)
  fitted for Moldova, over wet and dry years alike. The fitted coefficients, the anchor factors
  and the scatter below are pinned in `config.py`, and a data test re-derives them.
- **Loss.** The fitted shortfall below trend at SPEI = −D, the way crop insurance measures loss
  against an expected yield. A year drier than normal but still above the expected yield is not
  a loss. A worse drought never loses less, and past the largest severity in the data the curve
  stays flat rather than extrapolate.
- **Uncertainty.** Refits on 1,000 resamples of whole years. Districts in one year share its
  weather, so resampling district-years would pretend there were 35 times more droughts.
- **Level anchored to the literature.** Fitted on gridded SPEI, the curves come out flatter than
  the station-based curves in the literature (see "Gridded SPEI" below). Each fitted shape is
  therefore scaled until its mean loss over years with SPEI-3 ≤ −1 equals Potopová et al. (2016,
  Table 6): 0.188 for winter wheat, 0.223 for sunflower, 0.305 for maize. The shape, the onset and
  the flat end come from the data; the level comes from the station-based study. Because loss is
  capped at the whole harvest, the factor is found by root-finding, not as a ratio of means.

| Crop | Fitted: loss at D = 1.5 / 2.0 (90 % interval) | Anchor factor | **Model: loss at D = 1.5 / 2.0** | Flat from D | AAL ratio, SPEI ~ N(0, 1): fitted → model |
|---|---|---|---|---|---|
| Winter wheat | 0.17 (0.08–0.27) / 0.27 (0.14–0.46) | ×1.14 | **0.19 / 0.31** | 1.98 | 3.1 % → 3.5 % |
| Sunflower | 0.08 (0.01–0.15) / 0.18 (0.09–0.25) | ×2.61 | **0.20 / 0.46** | 2.86 | 1.4 % → 3.5 % |
| Maize | 0.12 (0.00–0.27) / 0.37 (0.21–0.56) | ×2.23 | **0.26 / 0.82** | 2.84 | 2.4 % → 4.8 % |

The model's maize curve reaches the whole harvest from D ≈ 2.3; the 2007 national maize loss was
67 % (Potopová et al. 2016, Table 5a), and individual districts lost more.

The curves leave a lot unexplained: around them, yields scatter with a standard deviation of
0.27 (wheat), 0.23 (sunflower) and 0.45 (maize) of trend, and that scatter is shared between
districts in the same year (correlation 0.72, 0.54, 0.52). Both numbers are kept in `config.py`
because a parametric trigger can only be judged against losses that include this noise.

**Why loss starts late.** The trend was set in 2007–2023, a decade when most summers were dry, so
yields reach trend at a severity of about 1 and fall below it only after that. Measuring loss
from a "normal-climate" yield instead would lean on the few wet years in the record (maize's
include the 2021 bumper crop, 80 % over trend) and roughly triple the maize AAL ratio. The drier
recent climate belongs in the hazard, not the curve: see the trend under Synthetic hazard.

**What it leaves out, and which way it leans:**

- **Gridded SPEI flattens the fitted curves, so the level is borrowed.** The cells are a
  smoothed, noisy stand-in for each district's drought, and noise in a predictor pulls a fitted
  slope towards zero (regression dilution). Fitted, the maize and sunflower curves give about half
  the loss Potopová et al. (2016) found with station SPEI; the hazard is generated at station
  locations, so the model uses the anchored level. The anchor carries its own assumptions: it is
  national, for 1962–2012, and scaling a curve multiplies loss without moving where it starts.
- **One number per crop sets the level.** Loss in money scales with the anchor factor, and the
  anchor's own uncertainty is not quantified; the 90 % intervals above describe the fitted shape.
- **Few droughts.** 17 years with about five severe ones; the intervals above are wide.
- **Commercial yields only.** The NBS district yields cover farms of 10 ha or more; household
  maize may respond differently.
- **Winter wheat stops at D = 1.98.** No June in 2007–2023 was drier, so harsher wheat droughts
  get the D = 1.98 loss, although the 2007 national wheat loss of 50 % suggests more.

## Loss

`python -m drought_loss loss <hazard folder>` runs each crop's hazard, exposure and impact
function through CLIMADA, then builds the annual view from a year loss table (every year, crop
and district):

- **AAL** is the mean annual loss. Means add, so the crops' AALs sum to the total.
- **Exceedance curve.** The loss exceeded on average once every T years, from each year's total
  over all crops and districts (the aggregate, or AEP, view: one drought year hits all three
  crops). It uses CLIMADA's rule, the k-th largest of N years has return period N / k, and a test
  checks it gives the same numbers as CLIMADA's own curve.
- **No return period beyond the record.** From 60 years the worst year is all there is; CLIMADA
  would return it for any longer return period, so longer ones are refused.

Results, all producers (commercial farms only in brackets), synthetic hazard:

| | 60-year record (seed 42) | 10,000-year catalogue |
|---|---|---|
| **AAL** | $39.9 M ($30.5 M), 90 % interval $24–56 M | **$35.1 M ($25.8 M)** |
| AAL / exposure | 4.35 % | 3.82 % |
| 1-in-10 years | $150 M | $108 M ($80 M) |
| 1-in-20 | $212 M | $196 M ($138 M) |
| 1-in-50 | $359 M | $308 M ($225 M) |
| 1-in-100 | not reported | $409 M ($290 M) |
| 1-in-250 | not reported | $514 M ($368 M) |
| Worst year | $403 M | $739 M (80 % of exposure) |

| AAL by crop (10,000 years) | US$ M | Loss ratio | Analytic loss ratio, SPEI ~ N(0, 1) |
|---|---|---|---|
| Winter wheat | 8.2 | 3.51 % | 3.55 % |
| Sunflower | 13.2 | 3.43 % | 3.54 % |
| Maize | 13.6 | 4.56 % | 4.84 % |

**Reading it:**

- **One 60-year record is a noisy sample.** Its AAL is 14 % above the catalogue's, well inside
  the interval from resampling its years; with 60 years, every number above is uncertain by tens
  of percent. The catalogue pins the model's own answer down, not the real world's.
- **The pieces agree.** Each crop's loss ratio in the catalogue matches the analytic AAL ratio of
  its curve under standard-normal SPEI, as it should: the interpolation keeps SPEI standard normal
  at every district. The remaining gap is sampling noise; maize loss sits in the tail, and five
  other 2,000-year seeds put it anywhere from 4.2 % to 5.0 %. CLIMADA's losses equal a direct
  computation from the same severity to six decimals.
- **Diversification shows in the tail.** At 1-in-100 the crops' separate losses add up to $522 M,
  against $409 M for their annual total: one crop's worst year is not always another's. At
  1-in-2 it is the other way round, because small losses in different years add up.
- **District ranking reflects exposure only.** The synthetic hazard has no regional climate
  differences, so the districts with the largest AAL (Drochia, Gagauzia, Floresti) are simply the
  ones with the most crop value, and loss ratios differ only through crop mix (3.5–4.0 %).

### Current-climate sensitivity

Every number above assumes a stationary climate centred on the open cells' 1950–2023 normal.
Since 2001, summers have run drier. `python -m drought_loss hazard <csv> --climate recent`
shifts each crop month's SPEI-3, at every district after interpolation, to its 2001–2023 mean in
the open cells, and the same 10,000-year catalogue is run again:

| Crop (month) | SPEI-3 shift since 2001 | Standard error (23 years) |
|---|---|---|
| Winter wheat (June) | −0.31 | 0.21 |
| Sunflower (July) | −0.41 | 0.21 |
| Maize (August) | −0.59 | 0.19 |

| All producers | Stationary climate | Recent climate | Ratio |
|---|---|---|---|
| **AAL** | $35.1 M (3.8 %) | **$80.9 M (8.8 %)** | ×2.3 |
| Maize / sunflower / wheat AAL | $13.6 / 13.2 / 8.2 M | $39.6 / 28.4 / 13.0 M | ×2.9 / ×2.2 / ×1.6 |
| 1-in-10 years | $108 M | $264 M | ×2.5 |
| 1-in-100 | $409 M | $578 M | ×1.4 |
| 1-in-250 | $514 M | $657 M | ×1.3 |

- **A small shift, a large effect.** Moving the mean by a third to a half of a standard deviation
  more than doubles AAL, because loss only starts at a severity of about 1 and then climbs
  steeply: a drier mean pushes many more years past that threshold. The tail rises less, because
  the worst years already approach the whole exposure.
- **The shift is uncertain.** With each shift one standard error wetter or drier, AAL is $60 M or
  $111 M (analytic); even the wetter end is well above the stationary $36 M. Only maize's
  August shift is clearly beyond year-to-year noise.
- **The pieces agree here too.** Simulated loss ratios (5.5 / 7.4 / 13.3 %) match the analytic
  values for the shifted climate (5.6 / 7.5 / 13.7 %).
- **What it is not.** A shifted mean of the last 23 years, not a climate projection: it assumes
  the spread and spatial pattern of droughts are unchanged, and says nothing about the future
  beyond "if recent summers are the new normal".

**What it leaves out:** losses count only the three crops, with prices held fixed.

## Parametric cover and basis risk

`python -m drought_loss parametric --cells <folder> --catalogue <hazard folder> ...` designs an
index cover that pays on each district's SPEI-3 in the crop's window, then asks two questions:
how well would it have matched what farmers actually lost, and what does it cost?

**Three payout rules, at the same price.** Each is scaled so its expected payout under the
stationary hazard equals the crop's modelled AAL, so they can be compared at equal cost:

| Rule | Pays | Winter wheat | Sunflower | Maize |
|---|---|---|---|---|
| Binary | a fixed share of insured value when SPEI-3 ≤ −1.5 | 53 % | 53 % | 72 % |
| Ramp | from nothing at SPEI-3 = −1.0 up to a limit at −2.0 | limit 48 % | 47 % | 65 % |
| Curve | the model's own damage curve | | | |

**Basis risk, measured against what happened.** Comparing payouts with modelled losses from the
same index would show almost no basis risk, by construction. So each rule is backtested against
the yield shortfall NBS recorded in 35 districts over 2007–2023, with SPEI from the open cells as
the index: 595 district-years per crop. "Severe" means at least 30 % below trend, "little" less
than 10 %.

| All three crops | Binary | Ramp | Curve |
|---|---|---|---|
| Severe district losses with no payout (of 322) | 37 % | **22 %** | 22 % |
| Payouts on districts with little loss | 29 % | 39 % | 38 % |
| Correlation of payout and loss, district / national | 0.53 / 0.66 | **0.58 / 0.66** | 0.56 / 0.65 |
| Hedge effectiveness, district / national | −0.31 / 0.15 | **0.14 / 0.32** | −0.35 / 0.07 |
| Payouts ÷ recorded losses, 2007–2023 | 1.31 | 1.17 | 1.31 |

Hedge effectiveness is the share of the loss's variance a payout removes, 1 − Var(loss − payout)
/ Var(loss): 1 is a perfect hedge, 0 no better than no cover, below 0 worse than none. It depends
on timing and size together; correlation measures timing alone, and the best any rescaling of a
payout can reach is the correlation squared.

**Reading it:**

- **At district level, basis risk is large whatever the design.** Correlations of 0.34–0.62 by
  crop mean that even a perfectly sized payout would remove at most 11–38 % of a district's loss
  variance. SPEI-3 in one month misses frost, wet years, pests and drought that falls outside the
  window, and the recorded loss counts all of them.
- **It shrinks when districts are added up.** Nationally the correlation rises to 0.66, because
  one district's noise offsets another's. That is the case for covers held by a government or an
  aggregator rather than by each farm.
- **The binary trigger is the worst design.** Its cliff edge at −1.5 misses 37 % of severe losses
  (58 % for wheat) and pays a fixed amount whether the drought was just over the line or extreme.
- **The ramp is the best, and the curve is not.** The ramp misses the fewest severe losses and is
  the only rule that helps at both levels. The curve, the most model-like payout, pays most on
  the steep top end of the damage curve, where an index error costs most.
- **Too much, in the wrong places.** Over 2007–2023 all three paid more than the recorded losses
  in total, and more than a fifth of payouts went to districts with little loss, which is why
  district hedge effectiveness can fall below zero even with positive correlation.

**Price.** On the 10,000-year catalogues, all three products (US$ M):

| | Expected payout | Payout standard deviation | 1-in-10 payout | 1-in-100 payout |
|---|---|---|---|---|
| Binary, stationary / recent climate | 35.0 / 80.7 | 80 / 124 | 127 / 274 | 390 / 500 |
| Ramp, stationary / recent climate | 35.4 / 76.5 | 71 / 106 | 124 / 242 | 333 / 428 |
| Curve, stationary / recent climate | 35.1 / 80.9 | 79 / 129 | 108 / 264 | 409 / 578 |

- **The expected payout is the pure premium**, before an insurer's costs and capital charge.
  Priced on the stationary climate it is $35 M; if recent summers are the new normal, $77–81 M.
- **Climate risk is pricing risk.** Played back on the 2007–2023 index, the same covers would have
  paid $136–153 M a year, more than even the recent-climate price. That decade began with the 2007
  drought, and the backtest index is gridded rather than station-like, so the comparison is
  rough, but its direction is clear: a cover priced on a long-run average in a drying climate
  loses money.
- **The ramp's limit protects the insurer too.** It has the lowest payout spread and 1-in-100
  payout of the three, because it can never pay more than its limit.

**What it leaves out:** one index location per district (its centroid), one month per crop, no
deductibles, loadings or reinsurance structure, and only 17 years of yields with about five
severe droughts behind the backtest.

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

python -m drought_loss download                 # boundaries, NBS tables, FAOSTAT prices (12 MB fetched)
python -m drought_loss exposure                 # crop value per district into data/processed
pytest                                          # everything (data tests skip without the cells)
pytest -m "not climada and not data"            # fast tests only
python -m drought_loss synthetic --years 60     # CSV into data/processed
python -m drought_loss hazard data\processed\synthetic_spei_60y_seed42.csv --out data\processed\hazard_60y
python -m drought_loss loss data\processed\hazard_60y --out data\processed\loss_60y

# The long catalogue (1.5 minutes end to end):
python -m drought_loss synthetic --years 10000
python -m drought_loss hazard data\processed\synthetic_spei_10000y_seed42.csv --out data\processed\hazard_10000y
python -m drought_loss loss data\processed\hazard_10000y --out data\processed\loss_10000y

# The current-climate sensitivity: the same catalogue, SPEI shifted to its 2001-2023 mean
python -m drought_loss hazard data\processed\synthetic_spei_10000y_seed42.csv --out data\processed\hazard_10000y_recent --climate recent
python -m drought_loss loss data\processed\hazard_10000y_recent --out data\processed\loss_10000y_recent

# The parametric cover: backtest on the open cells, priced on both catalogues
python -m drought_loss parametric --cells "F:\Trifan PhD data\Database_SPEI_NUTS" --catalogue data\processed\hazard_10000y --catalogue data\processed\hazard_10000y_recent

# Re-fit the generator, and run the data tests, with the open SPEI cell workbooks:
python -m drought_loss calibrate "F:\Trifan PhD data\Database_SPEI_NUTS"
python -m drought_loss vulnerability --cells "F:\Trifan PhD data\Database_SPEI_NUTS"
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
  __main__.py           command line: python -m drought_loss download | synthetic | hazard |
                        exposure | vulnerability | loss | parametric | calibrate
  config.py             paths, pinned inputs (SHA-256), stations, the generator's parameters
  downloads.py          fetching with polite retries; nothing is used until its SHA-256 matches
  synthetic.py          the synthetic SPEI generator and its calibration
  open_spei.py          reader for the open SPEI cell workbooks (calibration only)
  spei_input.py         checks station SPEI on the way in; keeps private results out of here
  boundaries.py         district boundaries: download, verify, centroids
  hazard.py             crop-season severity per district, and the CLIMADA hazard
  nbs.py                NBS crop statistics through the PX-Web API, and the district crosswalk
  fao.py                FAOSTAT producer prices for Moldova
  exposure.py           crop value per district, its reconciliation, and CLIMADA exposures
  vulnerability.py      yield anomalies, the curve fit, year bootstrap, CLIMADA impact functions
  loss.py               CLIMADA impacts, year loss table, AAL, exceedance curve, districts
  parametric.py         payout rules, fair pricing, backtest and basis-risk measures
tests/                  pytest suite (markers: `climada` loads CLIMADA, `data` needs the cells,
                        `raw` needs data/raw)
scripts/dev_env.ps1     prepares a PowerShell window
data/, outputs/         downloaded inputs and generated outputs (git-ignored)
```

## Licence

Code: MIT (see `LICENSE`). Data keeps its source licence:

- **District boundaries:** [geoBoundaries](https://www.geoboundaries.org) ADM1 for Moldova
  (Runfola et al. 2020, PLoS ONE 15(4): e0231866), CC BY 3.0 IGO.
- **Crop statistics:** Source: National Bureau of Statistics of the Republic of Moldova,
  [statbank.statistica.md](https://statbank.statistica.md), tables AGR020600reg and AGR020060,
  CC BY 4.0. The model converts units and combines them as described under Exposure.
- **Producer prices:** FAO, FAOSTAT Producer Prices (Moldova), CC BY 4.0.
- **Generator parameters and impact functions:** derived from CSIC's Global SPEI database
  (Beguería et al. 2014, Int. J. Climatol. 34:3001; Vicente-Serrano et al. 2010, J. Climate
  23:1696), which is made available under the Open Database License, together with the NBS
  yields above. The fitted numbers in `config.py` are a produced work of that database.
