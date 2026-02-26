import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# Inner -> outer stacking order (matches your digitizer categories)
STACK_ORDER = ["other_causes", "wounds", "preventable_disease"]

# More “plate-like” colors
CAT_COLOR = {
    "preventable_disease": "#2f5d7c",  # muted ink blue
    "wounds": "#b86b6b",               # muted rose/red
    "other_causes": "#2b2b2b",         # charcoal
}

LEGEND_PRETTY = {
    "preventable_disease": "Preventable disease (BLUE)",
    "wounds": "Wounds (RED)",
    "other_causes": "Other causes (BLACK)",
}


def month_labels_from_strings(months):
    import calendar
    out = []
    for m in months:
        y, mm = m.split("-")
        out.append(f"{calendar.month_abbr[int(mm)]}")
    return out


def load_and_prepare(csv_path: str):
    df = pd.read_csv(csv_path)

    if "is_missing" not in df.columns:
        df["is_missing"] = 0

    # Compute or clean area_rel
    if "area_rel" not in df.columns or df["area_rel"].isna().all():
        df["radius_px"] = pd.to_numeric(df["radius_px"], errors="coerce").fillna(0.0)
        df["area_rel"] = df["radius_px"] ** 2
    else:
        df["area_rel"] = pd.to_numeric(df["area_rel"], errors="coerce").fillna(0.0)

    df["is_missing"] = pd.to_numeric(df["is_missing"], errors="coerce").fillna(0).astype(int)
    df.loc[df["is_missing"] == 1, "area_rel"] = 0.0

    # Keep only known categories
    df = df[df["category"].isin(STACK_ORDER)].copy()

    # Preserve month order from file (important for matching your capture order)
    months = list(dict.fromkeys(df["month"].tolist()))
    return df, months


def pivot_area(df, months):
    table = (
        df.pivot_table(index="month", columns="category", values="area_rel", aggfunc="first")
        .reindex(months)
        .fillna(0.0)
    )
    for c in STACK_ORDER:
        if c not in table.columns:
            table[c] = 0.0
    return table[STACK_ORDER]


def draw_rose(ax, area_table, months, title, global_max):
    n = len(months)
    months = list(reversed(months))
    area_table = area_table.reindex(months)
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    width = 2 * np.pi / n

    # Stack in AREA space then convert to radii
    cum_area = area_table.cumsum(axis=1)

    if global_max <= 0:
        global_max = 1.0

    r_cum = np.sqrt(cum_area / global_max)

    # Match original orientation style
    ax.set_theta_direction(1)      # counterclockwise
    ax.set_theta_offset(np.pi)     # start at left (rotated 90° counterclockwise from top)

    prev = np.zeros(n)
    for cat in STACK_ORDER:
        outer = r_cum[cat].to_numpy()
        heights = outer - prev
        ax.bar(
            theta,
            heights,
            width=width,
            bottom=prev,
            align="edge",
            color=CAT_COLOR[cat],
            edgecolor="white",
            linewidth=0.7,
            alpha=0.97,
            label=cat
        )
        prev = outer

    # Month labels around circle (abbrev like original)
    ax.set_xticks(theta + width/2)
    ax.set_xticklabels(month_labels_from_strings(months), fontsize=9)

    # Set consistent radial limits for both plots (normalized to 0-1 scale)
    ax.set_ylim(0, 1.0)
    ax.set_yticklabels([])
    ax.grid(True, linewidth=0.5, alpha=0.35)
    ax.set_title(title, pad=14, fontsize=11, weight="bold")


def main():
    # Prefilled paths
    csv_left = "output_data_left.csv"    # Apr 1855 – Mar 1856
    csv_right = "output_data_right.csv"  # Apr 1854 – Mar 1855

    for p in (csv_left, csv_right):
        if not os.path.exists(p):
            raise FileNotFoundError(f"Missing {p}. Export CSV from the digitizer first.")

    # Load both
    dfL, monthsL = load_and_prepare(csv_left)
    dfR, monthsR = load_and_prepare(csv_right)
    areaL = pivot_area(dfL, monthsL)
    areaR = pivot_area(dfR, monthsR)

    cumL = areaL.cumsum(axis=1)
    cumR = areaR.cumsum(axis=1)

    global_max = max(
        float(cumL.max().max()),
        float(cumR.max().max())
    )

    # --- Plate layout like the original image (NO OVERLAP) ---
    fig = plt.figure(figsize=(14, 8), constrained_layout=True)

    # 2 rows: title row + plots row + footer row
    # 3 columns in plots row: left chart, right chart, legend column
    gs = fig.add_gridspec(
        nrows=3, ncols=3,
        height_ratios=[1.3, 8.5, 1.2],
        width_ratios=[1.0, 1.0, 0.55]
    )

    # Title across top (full width)
    ax_title = fig.add_subplot(gs[0, :])
    ax_title.axis("off")
    ax_title.text(
        0.5, 0.55,
        "DIAGRAM OF THE CAUSES OF MORTALITY\nIN THE ARMY IN THE EAST.",
        ha="center", va="center",
        fontsize=18, weight="bold", family="serif"
    )

    # Two polar plots
    ax_left  = fig.add_subplot(gs[1, 0], projection="polar")
    ax_right = fig.add_subplot(gs[1, 1], projection="polar")

    draw_rose(ax_left,  areaL, monthsL,  "APRIL 1855 to MARCH 1856.", global_max)
    draw_rose(ax_right, areaR, monthsR,  "APRIL 1854 to MARCH 1855.", global_max)

    # Legend column (separate axis so it never overlaps the polar plots)
    ax_leg = fig.add_subplot(gs[1, 2])
    ax_leg.axis("off")

    handles, labels = ax_right.get_legend_handles_labels()
    labels = [LEGEND_PRETTY.get(l, l) for l in labels]

    ax_leg.legend(
        handles, labels,
        loc="center left",
        frameon=False,
        fontsize=11
    )

    # Footer / note across bottom
    ax_note = fig.add_subplot(gs[2, :])
    ax_note.axis("off")
    ax_note.text(
        0.01, 0.5,
        "Color key: BLUE = Preventable disease, RED = Wounds, BLACK = Other causes. "
        "Wedge area ∝ value (radius²).",
        ha="left", va="center", fontsize=11
    )

    # Save PNG (no overlap guaranteed)
    out = "nightingale_plate.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    print(f"Saved: {out}")
    plt.show()

    # Title across top
    ax_title = fig.add_subplot(gs[0, :])
    ax_title.axis("off")
    ax_title.text(
        0.5, 0.55,
        "DIAGRAM OF THE CAUSES OF MORTALITY\nIN THE ARMY IN THE EAST.",
        ha="center", va="center",
        fontsize=18, weight="bold", family="serif"
    )

    # Left rose (smaller, like original)
    ax_left = fig.add_subplot(gs[1, 1], projection="polar")
    draw_rose(ax_left, areaL, monthsL, "APRIL 1855 to MARCH 1856.")

    # Right rose (larger)
    ax_right = fig.add_subplot(gs[1, 3], projection="polar")
    draw_rose(ax_right, areaR, monthsR, "APRIL 1854 to MARCH 1855.")

    # Bottom note area (optional – you can paste your assignment explanation here)
    ax_note = fig.add_subplot(gs[2, :])
    ax_note.axis("off")
    ax_note.text(
        0.01, 0.5,
        "Color key: BLUE = Preventable disease, RED = Wounds, BLACK = Other causes. "
        "Wedge area ∝ value (radius²).",
        ha="left", va="center", fontsize=11
    )

    # Single legend (right side)
    handles, labels = ax_right.get_legend_handles_labels()
    labels = [LEGEND_PRETTY.get(l, l) for l in labels]
    fig.legend(handles, labels, loc="center right", bbox_to_anchor=(0.98, 0.35),
               frameon=False, fontsize=11)

    # Save PNG
    out = "nightingale_plate.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    print(f"Saved: {out}")

    plt.show()


if __name__ == "__main__":
    main()