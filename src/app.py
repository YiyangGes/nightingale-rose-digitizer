from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from tkinter import messagebox

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from matplotlib.widgets import Button
from PIL import Image

# ----------------------------
# Diagram-specific configuration
# ----------------------------

DIAGRAMS = {
    # Crop boxes are in *fraction of image* coordinates: (left, top, right, bottom)
    "right": {
        "title": "Diagram 1 (Right): April 1854 to March 1855",
        "months": [
            "1854-04","1854-05","1854-06","1854-07","1854-08","1854-09",
            "1854-10","1854-11","1854-12","1855-01","1855-02","1855-03",
        ],
        "crop_frac": (0.48, 0.05, 0.99, 0.95),
    },
    "left": {
        "title": "Diagram 2 (Left): April 1855 to March 1856",
        "months": [
            "1855-04","1855-05","1855-06","1855-07","1855-08","1855-09",
            "1855-10","1855-11","1855-12","1856-01","1856-02","1856-03",
        ],
        "crop_frac": (0.02, 0.06, 0.44, 0.76),  # <-- TWEAK IF NEEDED
    },
}

CATEGORIES = ["preventable_disease", "wounds", "other_causes"]

CAT_TO_COLORNAME = {
    "preventable_disease": "BLUE",
    "wounds": "RED",
    "other_causes": "BLACK",
}

# ----------------------------
# UI Theme (modern / clean)
# ----------------------------

THEME = {
    # Surfaces
    "fig_bg": "#F6F7FB",
    "card_bg": "#FFFFFF",
    "card_border": "#E6E8F0",

    # Text
    "text": "#111827",
    "muted": "#6B7280",
    "accent": "#2563EB",   # blue
    "danger": "#DC2626",   # red
    "ok": "#059669",       # green

    # Buttons
    "btn_bg": "#FFFFFF",
    "btn_hover": "#EEF2FF",
    "btn_border": "#D1D5DB",

    # Overlays
    "center": "#111827",
    "line": "#334155",
    "point": "#0F172A",
    "highlight": "#2563EB",
}

def apply_theme():
    # A few global rcParams that make Matplotlib feel less “default”.
    mpl.rcParams.update({
        "figure.facecolor": THEME["fig_bg"],
        "axes.facecolor": THEME["fig_bg"],
        "savefig.facecolor": THEME["fig_bg"],
        "font.size": 11,
        "font.family": "DejaVu Sans",
        "axes.titlesize": 13,
        "axes.titleweight": "semibold",
        "text.color": THEME["text"],
        "axes.labelcolor": THEME["text"],
        "xtick.color": THEME["muted"],
        "ytick.color": THEME["muted"],
    })


# ----------------------------
# Data model
# ----------------------------

@dataclass
class Measurement:
    radius_px: float
    click_xy: Optional[Tuple[float, float]]  # None if missing
    is_missing: bool = False

@dataclass
class ProjectData:
    image_path: str
    diagram_key: str
    center_xy: Optional[Tuple[float, float]]  # in CROPPED coords
    months: List[str]
    categories: List[str]
    data: Dict[str, Dict[str, Optional[Measurement]]]


def make_empty_project(image_path: str, diagram_key: str, months: List[str], categories: List[str]) -> ProjectData:
    data: Dict[str, Dict[str, Optional[Measurement]]] = {}
    for m in months:
        data[m] = {c: None for c in categories}
    return ProjectData(
        image_path=image_path,
        diagram_key=diagram_key,
        center_xy=None,
        months=months,
        categories=categories,
        data=data,
    )


# ----------------------------
# Helpers
# ----------------------------

def dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])

def safe_write_json(path: str, payload: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def project_to_dict(p: ProjectData) -> dict:
    out = {
        "image_path": p.image_path,
        "diagram_key": p.diagram_key,
        "center_xy": list(p.center_xy) if p.center_xy else None,
        "months": p.months,
        "categories": p.categories,
        "data": {},
    }
    for m in p.months:
        out["data"][m] = {}
        for c in p.categories:
            meas = p.data[m][c]
            if meas is None:
                out["data"][m][c] = None
            else:
                out["data"][m][c] = {
                    "radius_px": meas.radius_px,
                    "click_xy": [meas.click_xy[0], meas.click_xy[1]] if meas.click_xy else None,
                    "is_missing": meas.is_missing,
                }
    return out

def dict_to_project(d: dict) -> ProjectData:
    p = ProjectData(
        image_path=d["image_path"],
        diagram_key=d["diagram_key"],
        center_xy=tuple(d["center_xy"]) if d["center_xy"] else None,
        months=d["months"],
        categories=d["categories"],
        data={},
    )
    for m in p.months:
        p.data[m] = {}
        for c in p.categories:
            v = d["data"][m][c]
            if v is None:
                p.data[m][c] = None
            else:
                click_xy = None
                if v.get("click_xy") is not None:
                    click_xy = (float(v["click_xy"][0]), float(v["click_xy"][1]))
                p.data[m][c] = Measurement(
                    radius_px=float(v["radius_px"]),
                    click_xy=click_xy,
                    is_missing=v.get("is_missing", False),
                )
    return p

def crop_image_by_frac(img: Image.Image, crop_frac: Tuple[float, float, float, float]) -> Image.Image:
    w, h = img.size
    l, t, r, b = crop_frac
    box = (int(l * w), int(t * h), int(r * w), int(b * h))
    return img.crop(box)

def progress_bar(done: int, total: int, width: int = 18) -> str:
    if total <= 0:
        return ""
    frac = max(0.0, min(1.0, done / total))
    filled = int(round(frac * width))
    return "█" * filled + "░" * (width - filled)


# ----------------------------
# App
# ----------------------------

class DigitizerApp:
    def __init__(self, image_path: str, diagram_key: str):
        apply_theme()

        if diagram_key not in DIAGRAMS:
            raise ValueError(f"diagram_key must be one of {list(DIAGRAMS.keys())}")

        self.diagram_key = diagram_key
        self.diagram_title = DIAGRAMS[diagram_key]["title"]
        self.months = DIAGRAMS[diagram_key]["months"]
        self.crop_frac = DIAGRAMS[diagram_key]["crop_frac"]

        self.save_path = f"progress_{diagram_key}.json"
        self.csv_path = f"output_data_{diagram_key}.csv"

        self.month_i = 0
        self.cat_i = 0
        self.setting_center = False
        self.processing_click = False

        self.undo_stack: List[Tuple[str, str, Optional[Measurement]]] = []

        # Overlay artists
        self.center_artist = None
        self.point_artists = []
        self.line_artists = []
        self.preview_point = None
        self.preview_line = None
        self.preview_hidden = False

        # Load or start project
        if os.path.exists(self.save_path):
            try:
                with open(self.save_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self.project = dict_to_project(loaded)
            except Exception:
                self.project = make_empty_project(image_path, diagram_key, self.months, CATEGORIES)
        else:
            self.project = make_empty_project(image_path, diagram_key, self.months, CATEGORIES)

        self._find_first_unfilled()

        # --- Layout: header (top), main (sidebar + image), toolbar (bottom) ---
        self.fig = plt.figure(figsize=(15, 8.6), constrained_layout=False)
        self.fig.subplots_adjust(left=0.02, right=0.985, top=0.97, bottom=0.06, wspace=0.02, hspace=0.05)
        # More space for the header (prevents overlap on high DPI displays)
        gs = self.fig.add_gridspec(
            nrows=3, ncols=2,
            height_ratios=[1.9, 17.0, 3.1],   # <- was [1.9, 17.6, 2.5]
            width_ratios=[7.5, 16.5]
        )
        
        self.ax_header = self.fig.add_subplot(gs[0, :])
        self.ax_status = self.fig.add_subplot(gs[1, 0])
        self.ax = self.fig.add_subplot(gs[1, 1])
        self.ax_buttons = self.fig.add_subplot(gs[2, :])

        self._init_header()
        self._load_image(image_path)
        self._init_sidebar()
        self._init_toolbar()

        self._redraw_overlays()
        self._update_header()
        self._update_status_text()

        self.fig.canvas.mpl_connect("button_press_event", self.on_click)
        self.fig.canvas.mpl_connect("motion_notify_event", self.on_move)
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)

    # ----------------------------
    # UI construction
    # ----------------------------

    def _init_header(self):
        self.ax_header.set_axis_off()
        # Header “card”
        self._header_card = FancyBboxPatch(
            (0.0, 0.05), 1.0, 0.9,
            boxstyle="round,pad=0.012,rounding_size=14",
            transform=self.ax_header.transAxes,
            linewidth=1.0,
            edgecolor=THEME["card_border"],
            facecolor=THEME["card_bg"],
        )
        self.ax_header.add_patch(self._header_card)

        self.header_title = self.ax_header.text(
            0.02, 0.67, self.diagram_title,
            transform=self.ax_header.transAxes,
            ha="left", va="center",
            fontsize=14, fontweight="semibold", color=THEME["text"]
        )
        self.header_sub = self.ax_header.text(
            0.02, 0.30, "",
            transform=self.ax_header.transAxes,
            ha="left", va="center",
            fontsize=11, color=THEME["muted"]
        )
        self.header_right = self.ax_header.text(
            0.98, 0.50, "",
            transform=self.ax_header.transAxes,
            ha="right", va="center",
            fontsize=11, color=THEME["muted"]
        )

    def _load_image(self, image_path: str):
        full = Image.open(image_path)
        self.image = crop_image_by_frac(full, self.crop_frac)

        self.ax.imshow(self.image)
        self.ax.set_axis_off()

        # subtle “image card” border
        for spine in self.ax.spines.values():
            spine.set_visible(True)
            spine.set_linewidth(1.0)
            spine.set_edgecolor(THEME["card_border"])

    def _init_sidebar(self):
        self.ax_status.set_axis_off()

        # Card background
        self._status_card = FancyBboxPatch(
            (0.0, 0.0), 1.0, 1.0,
            boxstyle="round,pad=0.012,rounding_size=14",
            transform=self.ax_status.transAxes,
            linewidth=1.0,
            edgecolor=THEME["card_border"],
            facecolor=THEME["card_bg"],
        )
        self.ax_status.add_patch(self._status_card)

        self.status_title = self.ax_status.text(
            0.06, 0.95, "Instructions",
            transform=self.ax_status.transAxes,
            ha="left", va="top",
            fontsize=12, fontweight="semibold", color=THEME["text"]
        )

        self.status = self.ax_status.text(
            0.06, 0.90, "",
            va="top", ha="left",
            transform=self.ax_status.transAxes,
            fontsize=10.4,
            color=THEME["text"],
            wrap=True
        )

    def _init_toolbar(self):
        import math

        self.ax_buttons.set_axis_off()

        # Toolbar card
        self._toolbar_card = FancyBboxPatch(
            (0.0, 0.04), 1.0, 0.92,
            boxstyle="round,pad=0.012,rounding_size=14",
            transform=self.ax_buttons.transAxes,
            linewidth=1.0,
            edgecolor=THEME["card_border"],
            facecolor=THEME["card_bg"],
        )
        self.ax_buttons.add_patch(self._toolbar_card)
        

        # Two-row grouping to avoid overlap on smaller widths / high DPI:
        row1 = [
            ("NAV", [
                ("⦿ Set Center", self.toggle_center_mode),
                ("◀ Prev", self.prev_item),
                ("Next ▶", self.next_item),
                ("↩ Undo", self.undo),
            ]),
            ("EDIT", [
                ("⊘ Mark Missing", self.mark_missing),
                ("↻ Remeasure", self.remeasure_current),
                ("⇥ Next Unfilled", self.jump_to_unfilled),
                ("🧹 Clear All", self.clear_all),
            ]),
        ]
        row2 = [
            ("DATA", [
                ("💾 Save", self.save),
                ("⟳ Reload", self.reload),
                ("⇩ Export CSV", self.export_csv),
            ]),
        ]

        # Layout parameters
        outer_left = 0.018
        outer_right = 0.018
        row_gap_y = 0.10

        # Button sizing within each row
        # Each row has its own y-band inside the toolbar card
        row_h = (0.92 - row_gap_y) / 2.0
        row1_y = 0.04 + row_h + row_gap_y
        row2_y = 0.04

        # Button band inside each row
        # Leave more headroom for the group label (prevents it being covered)
        btn_band_y = 0.08
        btn_band_h = 0.66

        def draw_row(groups, y0, y1):
            # groups share the row width
            group_gap = 0.018
            n_groups = len(groups)
            usable = 1.0 - outer_left - outer_right - group_gap * (n_groups - 1)
            group_w = usable / n_groups

            for gi, (gname, items) in enumerate(groups):
                gx = outer_left + gi * (group_w + group_gap)

                # Group label (float above buttons; white bbox so borders don't cover it)
                self.ax_buttons.text(
                    gx + 0.010, y1 - 0.01, gname,
                    transform=self.ax_buttons.transAxes,
                    ha="left", va="top",
                    fontsize=8.8, color=THEME["muted"], fontweight="semibold",
                    bbox=dict(facecolor=THEME["card_bg"], edgecolor="none", pad=0.2)
                )

                # Buttons in this group (single row inside the group)
                n = len(items)
                inner_left = gx + 0.010
                inner_right = gx + group_w - 0.010
                inner_gap = 0.012

                inner_usable = inner_right - inner_left - inner_gap * (n - 1)
                bw = inner_usable / n

                for i, (label, cb) in enumerate(items):
                    bx = inner_left + i * (bw + inner_gap)
                    by = y0 + btn_band_y * (y1 - y0)
                    bh = btn_band_h * (y1 - y0)

                    axb = self.ax_buttons.inset_axes([bx, by, bw, bh])
                    axb.set_facecolor(THEME["btn_bg"])
                    for sp in axb.spines.values():
                        sp.set_edgecolor(THEME["btn_border"])
                        sp.set_linewidth(1.0)

                    btn = Button(axb, label, color=THEME["btn_bg"], hovercolor=THEME["btn_hover"])
                    btn.label.set_fontsize(10)     # slightly smaller to prevent clipping
                    btn.label.set_color(THEME["text"])
                    btn.on_clicked(cb)
                    self._buttons.append(btn)

        self._buttons = []
        draw_row(row1, row1_y, row1_y + row_h)
        draw_row(row2, row2_y, row2_y + row_h)

    # ----------------------------
    # Workflow
    # ----------------------------

    def current_month_cat(self) -> Tuple[str, str]:
        return self.project.months[self.month_i], self.project.categories[self.cat_i]

    def toggle_center_mode(self, _event=None):
        self.setting_center = not self.setting_center
        self._update_header()
        self._update_status_text()

    def on_click(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return

        if self.processing_click:
            return

        x, y = float(event.xdata), float(event.ydata)

        # Right-click toggles preview visibility
        if event.button == 3 and self.project.center_xy is not None:
            self.preview_hidden = not self.preview_hidden
            if self.preview_hidden:
                if self.preview_point is not None:
                    self.preview_point.remove()
                    self.preview_point = None
                if self.preview_line is not None:
                    self.preview_line.remove()
                    self.preview_line = None
            else:
                cx, cy = self.project.center_xy
                self._draw_preview(cx, cy, x, y)
            self.fig.canvas.draw_idle()
            return

        # Left click only
        if event.button != 1:
            return

        # Ignore click when zoom/pan is active
        if self.fig.canvas.toolbar and self.fig.canvas.toolbar.mode:
            return

        self.processing_click = True
        try:
            # Set center
            if self.setting_center:
                self.project.center_xy = (x, y)
                self.setting_center = False
                self.save()
                self._redraw_overlays()
                self._update_header()
                self._update_status_text()
                return

            # Measure
            if self.project.center_xy is None:
                self.status.set_text("Set the center first: click “Set Center”, then click the hub where wedges meet.")
                self.fig.canvas.draw_idle()
                return

            month, cat = self.current_month_cat()
            prev = self.project.data[month][cat]
            self.undo_stack.append((month, cat, prev))

            r = dist(self.project.center_xy, (x, y))
            self.project.data[month][cat] = Measurement(radius_px=r, click_xy=(x, y))

            self.preview_hidden = False

            self.save()
            self._redraw_overlays()
            self._update_header()
            self._update_status_text()

            self.fig.canvas.flush_events()
            self.next_item()
        finally:
            self.processing_click = False

    def on_move(self, event):
        if event.inaxes != self.ax or self.project.center_xy is None:
            return
        if event.xdata is None or event.ydata is None:
            return
        if self.preview_hidden:
            return

        cx, cy = self.project.center_xy
        x, y = float(event.xdata), float(event.ydata)
        self._draw_preview(cx, cy, x, y)

    def _draw_preview(self, cx, cy, x, y):
        if self.preview_point is not None:
            self.preview_point.remove()
            self.preview_point = None
        if self.preview_line is not None:
            self.preview_line.remove()
            self.preview_line = None

        self.preview_point = self.ax.plot(
            x, y, marker="+", markersize=12, markeredgewidth=2.0, color=THEME["highlight"]
        )[0]
        self.preview_line = self.ax.plot(
            [cx, x], [cy, y], linewidth=2.0, color=THEME["highlight"], alpha=0.9
        )[0]
        self.fig.canvas.draw_idle()

    def on_key(self, event):
        key = (event.key or "").lower()

        if key in ("ctrl+z", "cmd+z"):
            self.undo()
            return
        if key == "m":
            self.mark_missing()
            return
        if key in ("right", "down"):
            self.next_item()
            return
        if key in ("left", "up"):
            self.prev_item()
            return

    def next_item(self, _event=None):
        if self.month_i == len(self.project.months) - 1 and self.cat_i == len(self.project.categories) - 1:
            return
        self.cat_i += 1
        if self.cat_i >= len(self.project.categories):
            self.cat_i = 0
            self.month_i += 1
        self._redraw_overlays()
        self._update_header()
        self._update_status_text()

    def prev_item(self, _event=None):
        if self.month_i == 0 and self.cat_i == 0:
            return
        self.cat_i -= 1
        if self.cat_i < 0:
            self.cat_i = len(self.project.categories) - 1
            self.month_i -= 1
        self._redraw_overlays()
        self._update_header()
        self._update_status_text()

    def undo(self, _event=None):
        if not self.undo_stack:
            return
        month, cat, prev = self.undo_stack.pop()
        self.project.data[month][cat] = prev
        self.month_i = self.project.months.index(month)
        self.cat_i = self.project.categories.index(cat)

        self.preview_hidden = False
        if self.preview_point is not None:
            self.preview_point.remove()
            self.preview_point = None
        if self.preview_line is not None:
            self.preview_line.remove()
            self.preview_line = None

        self.save()
        self._redraw_overlays()
        self._update_header()
        self._update_status_text()

    def clear_all(self, _event=None):
        result = messagebox.askyesno(
            "Clear All Measurements",
            "Are you sure you want to clear all measurements?\n\n"
            "This will keep the center point but remove all wedge measurements.\n\n"
            "This action cannot be undone.",
            icon="warning"
        )
        if not result:
            return

        for m in self.project.months:
            for c in self.project.categories:
                self.project.data[m][c] = None

        self.undo_stack.clear()
        self.month_i = 0
        self.cat_i = 0

        self.preview_hidden = False
        if self.preview_point is not None:
            self.preview_point.remove()
            self.preview_point = None
        if self.preview_line is not None:
            self.preview_line.remove()
            self.preview_line = None

        self.save()
        self._redraw_overlays()
        self._update_header()
        self._update_status_text()

    def _find_first_unfilled(self):
        for month_i, m in enumerate(self.project.months):
            for cat_i, c in enumerate(self.project.categories):
                if self.project.data[m][c] is None:
                    self.month_i = month_i
                    self.cat_i = cat_i
                    return
        self.month_i = len(self.project.months) - 1
        self.cat_i = len(self.project.categories) - 1

    def jump_to_unfilled(self, _event=None):
        self._find_first_unfilled()
        self._redraw_overlays()
        self._update_header()
        self._update_status_text()

    def mark_missing(self, _event=None):
        if self.project.center_xy is None:
            self.status.set_text("Set center first.")
            self.fig.canvas.draw_idle()
            return

        month, cat = self.current_month_cat()
        prev = self.project.data[month][cat]
        self.undo_stack.append((month, cat, prev))

        self.project.data[month][cat] = Measurement(radius_px=0.0, click_xy=None, is_missing=True)

        self.preview_hidden = False
        if self.preview_point is not None:
            self.preview_point.remove()
            self.preview_point = None
        if self.preview_line is not None:
            self.preview_line.remove()
            self.preview_line = None

        self.save()
        self.next_item()

    def remeasure_current(self, _event=None):
        if self.project.center_xy is None:
            self.status.set_text("Set center first.")
            self.fig.canvas.draw_idle()
            return

        month, cat = self.current_month_cat()
        prev = self.project.data[month][cat]
        
        # Only allow remeasure if there's actually something to clear
        if prev is None:
            self.status.set_text("Nothing to remeasure.")
            self.fig.canvas.draw_idle()
            return

        self.undo_stack.append((month, cat, prev))
        self.project.data[month][cat] = None

        self.preview_hidden = False
        if self.preview_point is not None:
            self.preview_point.remove()
            self.preview_point = None
        if self.preview_line is not None:
            self.preview_line.remove()
            self.preview_line = None

        self.save()
        self._redraw_overlays()
        self._update_header()
        self._update_status_text()

    # ----------------------------
    # Save / Load / Export
    # ----------------------------

    def save(self, _event=None):
        safe_write_json(self.save_path, project_to_dict(self.project))
        self.fig.canvas.draw_idle()

    def reload(self, _event=None):
        if not os.path.exists(self.save_path):
            return
        with open(self.save_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.project = dict_to_project(loaded)
        self.undo_stack.clear()
        self._redraw_overlays()
        self._update_header()
        self._update_status_text()

    def export_csv(self, _event=None):
        if self.project.center_xy is None:
            self.status.set_text("Set center before exporting.")
            self.fig.canvas.draw_idle()
            return

        areas = []
        for m in self.project.months:
            for c in self.project.categories:
                meas = self.project.data[m][c]
                if meas is None or meas.is_missing:
                    continue
                areas.append(meas.radius_px ** 2)
        max_area = max(areas) if areas else 1.0

        with open(self.csv_path, "w", encoding="utf-8") as f:
            f.write("month,category,is_missing,radius_px,area_rel,area_norm,click_x,click_y\n")
            for m in self.project.months:
                for c in self.project.categories:
                    meas = self.project.data[m][c]
                    if meas is None:
                        f.write(f"{m},{c},,,,\n")
                    else:
                        is_missing = 1 if meas.is_missing else 0
                        area_rel = 0.0 if meas.is_missing else (meas.radius_px ** 2)
                        area_norm = area_rel / max_area if max_area else 0.0
                        if meas.click_xy is None:
                            f.write(f"{m},{c},{is_missing},{meas.radius_px:.6f},{area_rel:.6f},{area_norm:.6f},,\n")
                        else:
                            x, y = meas.click_xy
                            f.write(f"{m},{c},{is_missing},{meas.radius_px:.6f},{area_rel:.6f},{area_norm:.6f},{x:.3f},{y:.3f}\n")

        self._update_header()
        self._update_status_text()

    # ----------------------------
    # Drawing
    # ----------------------------

    def _clear_overlays(self):
        if self.center_artist is not None:
            self.center_artist.remove()
            self.center_artist = None

        for a in self.point_artists + self.line_artists:
            a.remove()
        self.point_artists.clear()
        self.line_artists.clear()

    def _redraw_overlays(self):
        self._clear_overlays()

        month, cat = self.current_month_cat()

        if self.project.center_xy is not None:
            cx, cy = self.project.center_xy
            # Center marker: crisp + visible
            self.center_artist = self.ax.plot(
                cx, cy,
                marker="x", markersize=10, markeredgewidth=2.2,
                color=THEME["center"]
            )[0]

            # Recorded points/lines
            for m in self.project.months:
                for c in self.project.categories:
                    # Skip current target - it will be drawn with highlight
                    if m == month and c == cat:
                        continue
                    meas = self.project.data[m][c]
                    if meas is None or meas.is_missing or meas.click_xy is None:
                        continue
                    x, y = meas.click_xy
                    p = self.ax.plot(
                        x, y, marker="o", markersize=4.2,
                        color=THEME["point"], alpha=0.95
                    )[0]
                    l = self.ax.plot(
                        [cx, x], [cy, y],
                        linewidth=1.15, color=THEME["line"], alpha=0.70
                    )[0]
                    self.point_artists.append(p)
                    self.line_artists.append(l)

            # Highlight current target if exists (with measurement)
            meas = self.project.data[month][cat]
            if meas is not None and meas.click_xy is not None:
                x, y = meas.click_xy
                # Draw a prominent hollow circle
                p = self.ax.plot(
                    x, y,
                    marker="o", markersize=14, fillstyle="none",
                    markeredgewidth=2.5, color=THEME["highlight"], alpha=0.95
                )[0]
                # Draw a highlighted line
                l = self.ax.plot(
                    [cx, x], [cy, y],
                    linewidth=2.5, color=THEME["highlight"], alpha=0.85, linestyle="-"
                )[0]
                self.point_artists.append(p)
                self.line_artists.append(l)
            else:
                # If current target is empty, draw a small guide circle at center
                p = self.ax.plot(
                    cx, cy,
                    marker="o", markersize=8, fillstyle="none",
                    markeredgewidth=1.5, color=THEME["highlight"], alpha=0.6
                )[0]
                self.point_artists.append(p)

        self.fig.canvas.draw_idle()

    def _update_header(self):
        month, cat = self.current_month_cat()

        done = sum(
            1 for m in self.project.months for c in self.project.categories
            if self.project.data[m][c] is not None
        )
        total = len(self.project.months) * len(self.project.categories)

        mode = "SET CENTER" if self.setting_center else "MEASURE"
        mode_color = THEME["danger"] if self.setting_center else THEME["ok"]

        sub = f"Now measuring: {month} — {cat} ({CAT_TO_COLORNAME.get(cat, 'UNKNOWN')})"
        self.header_sub.set_text(sub)

        self.header_right.set_text(
            f"Mode: {mode}   |   Progress: {done}/{total} {progress_bar(done, total)}"
        )
        self.header_right.set_color(THEME["muted"])
        # small “mode color hint” by changing title color slightly
        self.header_title.set_color(THEME["text"])
        if self.setting_center:
            self.header_sub.set_color(mode_color)
        else:
            self.header_sub.set_color(THEME["muted"])

    def _update_status_text(self):
        month, cat = self.current_month_cat()
        center = self.project.center_xy
        meas = self.project.data[month][cat]

        done = sum(
            1 for m in self.project.months for c in self.project.categories
            if self.project.data[m][c] is not None
        )
        total = len(self.project.months) * len(self.project.categories)

        mode = "SET CENTER" if self.setting_center else "MEASURE WEDGE"
        center_line = (
            f"Center: ({center[0]:.1f}, {center[1]:.1f})"
            if center else
            "Center: NOT SET"
        )

        if meas is None:
            meas_line = "Current value: not measured"
        elif meas.is_missing:
            meas_line = "Current value: marked missing (radius = 0)"
        else:
            meas_line = f"Current value: radius = {meas.radius_px:.1f}px"

        shortcuts = "Shortcuts: Ctrl+Z undo \n M mark missing \n Arrow keys prev/next \n Right click toggle preview"

        click_rules = (
            "Step 1 - Turn on set center mode and \n click the center point (hub where wedges meet)\n"
            "Step 2 - Turn on measure mode and click the wedges\n"
            "How to click\n"
            "• Click ONE point only\n"
            "• Click the OUTERMOST curved edge of that color\n"
            "• Click near the middle angle of the month slice\n"
            "• Avoid side corners and interior area\n\n"
            "You measure radius = distance(center → boundary)\n"
            "Area is proportional to radius²\n"
            "Note that when zoom bar is active,\nmeasuring clicks are ignored"
        )

        mapping = (
            "Color → Category\n"
            "• BLUE  = preventable_disease\n"
            "• RED   = wounds\n"
            "• BLACK = other_causes"
        )

        header = (
            f"{center_line}\n"
            f"Mode: {mode}\n\n"
            f"Target\n"
            f"  Month: {month}\n"
            f"  Category: {cat} ({CAT_TO_COLORNAME.get(cat, 'UNKNOWN')})\n"
            f"  {meas_line}\n\n"
            f"Progress: {done}/{total} {progress_bar(done, total)}\n\n"
            f"{shortcuts}\n\n"
        )

        self.status.set_text(header + click_rules + "\n\n" + mapping)
        self.fig.canvas.draw_idle()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Nightingale Rose Diagram Digitizer (two-diagram image)")
    parser.add_argument("--image", required=True, help="Path to the image (the one containing BOTH diagrams)")
    parser.add_argument("--diagram", choices=["right", "left"], required=True,
                        help="Which diagram to digitize: right (1854-04..1855-03) or left (1855-04..1856-03)")
    args = parser.parse_args()

    _app = DigitizerApp(image_path=args.image, diagram_key=args.diagram)
    plt.show()


if __name__ == "__main__":
    main()