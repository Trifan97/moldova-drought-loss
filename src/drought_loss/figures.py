"""The README's figures: exceedance curve, loss by district, damage curves.

Each figure is drawn twice, for light and dark page themes, from the public pipeline's outputs.
Colours come from a validated palette (blue, orange and aqua clear the colour-blind separation
checks in both modes), and every figure names its series in a legend as well as by colour.
"""

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")  # files only, no window

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.cm import ScalarMappable  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator  # noqa: E402

from drought_loss import config, hazard, loss  # noqa: E402
from drought_loss.synthetic import FloatArray  # noqa: E402

DPI = 200
# MOLDREF99 / Moldova TM: the national projection, transverse Mercator on 28.4° E, so north is
# up across the country and shapes and distances are true to well under 0.1 %.
MAP_CRS = 4026
# The figures must come from the synthetic, public runs only.
SOURCES = {
    "record": ("hazard_60y", "loss_60y"),
    "stationary": ("hazard_10000y", "loss_10000y"),
    "recent": ("hazard_10000y_recent", "loss_10000y_recent"),
}


@dataclass(frozen=True)
class Theme:
    name: str
    surface: str
    ink: str
    ink_secondary: str
    muted: str
    grid: str
    axis: str
    series: tuple[str, str, str]
    ramp: tuple[str, ...]  # sequential, from "near zero" to "most"
    no_data: str


# Blue sequential steps 100 to 700 of the reference palette.
BLUE_RAMP = ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b")

LIGHT = Theme(
    name="light",
    surface="#fcfcfb",
    ink="#0b0b0b",
    ink_secondary="#52514e",
    muted="#898781",
    grid="#e1e0d9",
    axis="#c3c2b7",
    series=("#2a78d6", "#eb6834", "#1baf7a"),
    ramp=BLUE_RAMP,
    no_data="#e1e0d9",
)
# Dark mode has its own steps: "near zero" recedes towards the dark surface.
DARK = Theme(
    name="dark",
    surface="#1a1a19",
    ink="#f0efec",
    ink_secondary="#c3c2b7",
    muted="#898781",
    grid="#2c2c2a",
    axis="#383835",
    series=("#3987e5", "#d95926", "#199e70"),
    ramp=BLUE_RAMP[::-1],
    no_data="#383835",
)


def styled(theme: Theme, width: float, height: float, ncols: int = 1) -> tuple[Figure, list[Axes]]:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Segoe UI", "Helvetica", "Arial", "DejaVu Sans"],
            "font.size": 9,
        }
    )
    fig, axes = plt.subplots(1, ncols, figsize=(width, height), dpi=DPI, squeeze=False)
    fig.patch.set_facecolor(theme.surface)
    for ax in axes[0]:
        ax.set_facecolor(theme.surface)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(theme.axis)
            ax.spines[side].set_linewidth(0.8)
        ax.tick_params(colors=theme.muted, labelcolor=theme.ink_secondary, length=0, pad=4)
        ax.grid(axis="y", color=theme.grid, linewidth=0.8)
        ax.set_axisbelow(True)
    return fig, list(axes[0])


def titles(fig: Figure, theme: Theme, title: str, subtitle: str) -> None:
    fig.text(0.02, 0.965, title, color=theme.ink, fontsize=12, fontweight="semibold", va="top")
    fig.text(0.02, 0.905, subtitle, color=theme.ink_secondary, fontsize=9, va="top")


def check_public(processed: Path) -> None:
    """Refuse to draw from any hazard that came from private data."""
    for hazard_dir, _ in SOURCES.values():
        record = hazard.read_provenance(processed / hazard_dir)
        if config.PRIVATE_NAME.search(record["spei_file"]):
            raise SystemExit(f"{hazard_dir} comes from private data; figures are public-only")


def annual_totals(loss_dir: Path) -> pd.Series:
    return loss.annual_losses(pd.read_csv(loss_dir / "year_loss_table.csv"))


def exceedance_points(annual: pd.Series) -> tuple[FloatArray, FloatArray]:
    """Return period and loss of every year: the k-th largest of N has return period N / k."""
    descending = np.sort(annual.to_numpy(dtype=np.float64))[::-1]
    periods = len(descending) / np.arange(1, len(descending) + 1)
    return periods.astype(np.float64), descending


def plot_exceedance(
    record: pd.Series, stationary: pd.Series, recent: pd.Series, theme: Theme, path: Path
) -> None:
    fig, (ax,) = styled(theme, 8.0, 4.6)
    fig.subplots_adjust(left=0.09, right=0.80, top=0.80, bottom=0.13)
    m = 1e6
    longest = 1000  # a tenth of the catalogue: enough years beyond every plotted point
    for annual, color, label in [
        (stationary, theme.series[0], "Stationary climate (10,000 years)"),
        (recent, theme.series[1], "Recent climate (10,000 years)"),
    ]:
        periods, losses = exceedance_points(annual)
        keep = (periods >= 1) & (periods <= longest)
        ax.plot(
            periods[keep],
            losses[keep] / m,
            color=color,
            linewidth=2,
            label=label,
            solid_capstyle="round",
            solid_joinstyle="round",
        )
        end = losses[keep][0] / m
        ax.annotate(
            f"{label.split(' (')[0]}\n${end:,.0f} M at 1-in-{longest:,}",
            (longest, end),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            fontsize=8.5,
            color=theme.ink_secondary,
        )
        at_100 = float(loss.exceedance(annual, [100])[100]) / m
        ax.plot(
            [100],
            [at_100],
            "o",
            color=color,
            markersize=6,
            markeredgecolor=theme.surface,
            markeredgewidth=1.5,
            zorder=4,
        )
        ax.annotate(
            f"${at_100:,.0f} M",
            (100, at_100),
            xytext=(-6, 7),
            textcoords="offset points",
            ha="right",
            fontsize=8.5,
            color=theme.ink,
        )
    periods, losses = exceedance_points(record)
    ax.plot(
        periods,
        losses / m,
        "o",
        color=theme.series[2],
        markersize=5,
        markeredgecolor=theme.surface,
        markeredgewidth=1.2,
        label="One 60-year record",
        zorder=3,
    )
    worst = losses[0] / m
    # The record's dots sit between the two curves, with no room for a label there, so the
    # label goes in the empty space below the stationary curve, with a leader to the worst year.
    ax.annotate(
        f"One 60-year record:\nits worst year, ${worst:,.0f} M",
        (periods[0], worst),
        xytext=(250, worst * 0.55),
        textcoords="data",
        ha="center",
        va="center",
        fontsize=8.5,
        color=theme.ink_secondary,
        arrowprops={
            "arrowstyle": "-",
            "color": theme.muted,
            "linewidth": 0.8,
            "shrinkA": 2,
            "shrinkB": 5,
        },
    )
    ax.axvline(100, color=theme.grid, linewidth=0.8, zorder=0)
    ax.set_xscale("log")
    ticks = [1, 2, 5, 10, 20, 50, 100, 250, 1000]
    ax.xaxis.set_major_locator(FixedLocator(ticks))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f} M"))
    ax.set_xlim(1, longest)
    ax.set_ylim(0, None)
    ax.set_xlabel("Return period (years)", color=theme.ink_secondary)
    legend = ax.legend(loc="upper left", frameon=False, fontsize=8.5, handlelength=1.6)
    for text in legend.get_texts():
        text.set_color(theme.ink_secondary)
    titles(
        fig,
        theme,
        "Loss exceedance curve: three crops, all producers",
        "Annual drought loss exceeded once in N years on average, synthetic hazard. "
        "A drier recent climate lifts the whole curve.",
    )
    fig.savefig(path, facecolor=theme.surface)
    plt.close(fig)


def plot_district_map(
    districts: gpd.GeoDataFrame, stationary: pd.Series, recent: pd.Series, theme: Theme, path: Path
) -> None:
    # North-up, Moldova is taller than it is wide, so the maps get height; positions in inches.
    height = 5.8
    fig, axes = styled(theme, 8.0, height, ncols=2)
    fig.subplots_adjust(
        left=0.02, right=0.98, top=1 - 1.3 / height, bottom=0.9 / height, wspace=0.02
    )
    m = 1e6
    vmax = float(max(stationary.max(), recent.max()) / m)
    cmap = LinearSegmentedColormap.from_list("sequential", list(theme.ramp))
    projected = districts.to_crs(MAP_CRS)
    for ax, aal, label in [
        (axes[0], stationary, "Stationary climate"),
        (axes[1], recent, "Recent climate"),
    ]:
        values = projected["shapeName"].map(aal / m)
        insured = values.notna()
        projected[~insured].plot(ax=ax, color=theme.no_data, edgecolor=theme.surface, linewidth=0.6)
        projected[insured].assign(aal=values[insured]).plot(
            ax=ax,
            column="aal",
            cmap=cmap,
            vmin=0,
            vmax=vmax,
            edgecolor=theme.surface,
            linewidth=0.6,
        )
        ax.set_axis_off()
        ax.set_title(
            f"{label}: national AAL ${aal.sum() / m:,.1f} M",
            color=theme.ink,
            fontsize=9.5,
            loc="left",
        )
    scale = fig.add_axes((0.30, 0.4 / height, 0.40, 0.125 / height))
    bar = fig.colorbar(
        ScalarMappable(cmap=cmap, norm=Normalize(0, vmax)),
        cax=scale,
        orientation="horizontal",
    )
    for spine in bar.ax.spines.values():  # the colour bar's outline is one of these
        spine.set_visible(False)
    bar.ax.tick_params(colors=theme.muted, labelcolor=theme.ink_secondary, length=0, labelsize=8)
    bar.set_ticks(np.arange(0, np.floor(vmax) + 1).tolist())
    bar.ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f} M"))
    bar.ax.xaxis.set_label_position("top")
    bar.set_label(
        "AAL per district, one colour scale for both maps",
        color=theme.ink_secondary,
        fontsize=8.5,
        labelpad=4,
    )
    legend = fig.legend(
        handles=[
            Patch(
                facecolor=theme.no_data, edgecolor="none", label="No exposure (left bank, Bender)"
            )
        ],
        loc="lower right",
        bbox_to_anchor=(0.98, 0.325 / height),
        frameon=False,
        fontsize=8,
    )
    for text in legend.get_texts():
        text.set_color(theme.ink_secondary)
    fig.text(
        0.02,
        0.325 / height,
        f"{projected.crs.name}\nprojection (EPSG:{MAP_CRS})",
        ha="left",
        va="bottom",
        fontsize=7.5,
        linespacing=1.4,
        color=theme.ink_secondary,
    )
    titles(
        fig,
        theme,
        "Average annual loss by district",
        "10,000-year synthetic catalogue, all producers. The synthetic hazard has no regional\n"
        "climate differences, so the pattern follows where the crops are.",
    )
    fig.savefig(path, facecolor=theme.surface)
    plt.close(fig)


def plot_damage_curves(curves: pd.DataFrame, theme: Theme, path: Path) -> None:
    crops = [("winter_wheat", "Winter wheat"), ("sunflower", "Sunflower"), ("maize", "Maize")]
    fig, axes = styled(theme, 9.0, 4.0, ncols=3)
    fig.subplots_adjust(left=0.07, right=0.98, top=0.66, bottom=0.16, wspace=0.12)
    for ax, (crop, label) in zip(axes, crops, strict=True):
        rows = curves[curves["crop"] == crop]
        d = rows["severity"].to_numpy()
        ax.fill_between(
            d,
            rows["fitted_low_90"],
            rows["fitted_high_90"],
            color=theme.muted,
            alpha=0.15,
            linewidth=0,
        )
        ax.plot(
            d,
            rows["loss_fitted"],
            color=theme.muted,
            linewidth=2,
            label="Fitted on open data, with 90 % interval",
        )
        ax.plot(
            d,
            rows["loss_anchored"],
            color=theme.series[0],
            linewidth=2,
            label="Model: anchored to Potopová et al. (2016)",
        )
        at_2 = float(rows.loc[np.isclose(rows["severity"], 2.0), "loss_anchored"].iloc[0])
        ax.plot(
            [2.0],
            [at_2],
            "o",
            color=theme.series[0],
            markersize=6,
            markeredgecolor=theme.surface,
            markeredgewidth=1.5,
            zorder=4,
        )
        ax.annotate(
            f"{at_2:.0%}",
            (2.0, at_2),
            xytext=(-6, 6),
            textcoords="offset points",
            ha="right",
            fontsize=8.5,
            color=theme.ink,
        )
        factor = config.VULNERABILITY_ANCHOR_SCALE[crop]
        ax.set_title(f"{label}  (anchor ×{factor:.2f})", color=theme.ink, fontsize=9.5, loc="left")
        ax.set_xlim(0, 3)
        ax.set_ylim(0, 1.02)
        ax.set_xticks([0, 1, 2, 3])
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
        if ax is not axes[0]:
            ax.tick_params(labelleft=False)
    axes[1].set_xlabel(
        "Drought severity D = −SPEI-3 in the crop's month", color=theme.ink_secondary
    )
    axes[0].set_ylabel("Share of expected harvest lost", color=theme.ink_secondary)
    handles, labels = axes[0].get_legend_handles_labels()
    legend = fig.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(0.06, 0.835),
        ncols=2,
        frameon=False,
        fontsize=8.5,
        handlelength=1.6,
    )
    for text in legend.get_texts():
        text.set_color(theme.ink_secondary)
    titles(
        fig,
        theme,
        "Damage curves: share of the harvest lost at each drought severity",
        "Shapes fitted on NBS district yields and open SPEI, 2007-2023; levels scaled to the "
        "station-based Moldovan study.",
    )
    fig.savefig(path, facecolor=theme.surface)
    plt.close(fig)


def render_all(processed: Path, boundaries_path: Path, out_dir: Path) -> list[Path]:
    check_public(processed)
    record = annual_totals(processed / SOURCES["record"][1])
    stationary = annual_totals(processed / SOURCES["stationary"][1])
    recent = annual_totals(processed / SOURCES["recent"][1])
    district_aal = {
        name: pd.read_csv(
            processed / SOURCES[name][1] / "aal_by_district.csv", index_col="district"
        )["aal_usd"]
        for name in ("stationary", "recent")
    }
    districts = gpd.read_file(boundaries_path)
    curves = pd.read_csv(processed / "vulnerability_open_cells.csv")
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for theme in (LIGHT, DARK):
        paths = {
            name: out_dir / f"{name}-{theme.name}.png"
            for name in ("exceedance", "district-map", "damage-curves")
        }
        plot_exceedance(record, stationary, recent, theme, paths["exceedance"])
        plot_district_map(
            districts,
            district_aal["stationary"],
            district_aal["recent"],
            theme,
            paths["district-map"],
        )
        plot_damage_curves(curves, theme, paths["damage-curves"])
        written.extend(paths.values())
    return written
