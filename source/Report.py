# TagLab
# A semi-automatic segmentation tool
#
# Copyright(C) 2026
# Perry Institute for Marine Science
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

"""
A PDF summary of what a map contains: the orthomosaic and DEM it is built from, the
rugosity of its surface, and the point counts and regions annotated on it.

Nothing here touches Qt. The figures are built against matplotlib's object API rather
than pyplot, because pyplot keeps global state that does not belong inside a running
application.
"""

import math
import os
import textwrap
from datetime import datetime

import numpy as np
import rasterio as rio

from matplotlib.figure import Figure
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import ListedColormap
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.lines import Line2D

from source import genutils
from source import RasterOps


# A cell has to be nearly covered before its rugosity means anything: the denominator is
# the whole cell, so a half-covered cell at the edge of the survey reports about half the
# ratio it should.
MIN_CELL_COVERAGE = 0.95

DEFAULT_CELL_SIZE_M = 1.0

# how much of the raster to read when a figure only needs to look at it
PREVIEW_MAX_SIDE = 1400

PAGE_SIZE = (11.69, 8.27)          # A4 landscape, inches

INK = "#1b2a2e"
MUTED = "#5d7175"
RULE = "#c9d6d6"
ACCENT = "#0a6c88"


def wilsonInterval(successes, total, z=1.96):
    """
    Confidence interval for a proportion, the way a point count should report one.

    The textbook normal interval misbehaves exactly where point counts live - a class
    seen two or three times in a thousand - giving bounds below zero and far too narrow
    a range. Wilson's does not, and it stays sensible at zero counts.
    """

    if total <= 0:
        return 0.0, 0.0

    p = successes / float(total)
    denominator = 1.0 + z * z / total
    centre = (p + z * z / (2.0 * total)) / denominator
    spread = (z / denominator) * math.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total * total))

    return max(0.0, centre - spread), min(1.0, centre + spread)


def labelColour(project, class_name):
    """The colour this class is drawn in, as a matplotlib RGB triple."""

    label = project.labels.get(class_name) if project is not None else None
    if label is None or not getattr(label, "fill", None):
        return (0.55, 0.57, 0.58)

    return tuple(max(0, min(255, int(c))) / 255.0 for c in label.fill[:3])


def _previewFactor(width, height, max_side=PREVIEW_MAX_SIDE):
    return max(1, int(math.ceil(max(width, height) / float(max_side))))


def readPreview(filename, max_side=PREVIEW_MAX_SIDE):
    """
    A small RGB copy of a raster, read decimated so the size of the file does not matter.
    """

    with rio.open(filename) as src:
        factor = _previewFactor(src.width, src.height, max_side)
        out_h = max(1, src.height // factor)
        out_w = max(1, src.width // factor)
        count = min(3, src.count)
        data = src.read(tuple(range(1, count + 1)), out_shape=(count, out_h, out_w))
        mask = src.dataset_mask(out_shape=(out_h, out_w)) > 0

    rgb = np.moveaxis(data, 0, -1).astype(np.float32)
    if rgb.shape[2] == 1:
        rgb = np.repeat(rgb, 3, axis=2)
    if rgb.max() > 0:
        rgb /= max(1.0, float(rgb.max()))

    rgba = np.dstack([rgb, mask.astype(np.float32)])

    return rgba


def readDemPreview(filename, max_side=PREVIEW_MAX_SIDE):
    """A small copy of a DEM, with nodata as NaN."""

    with rio.open(filename) as src:
        factor = _previewFactor(src.width, src.height, max_side)
        out_h = max(1, src.height // factor)
        out_w = max(1, src.width // factor)
        z = src.read(1, out_shape=(out_h, out_w)).astype(np.float32)
        nodata = src.nodata

    if nodata is not None:
        z[z == nodata] = np.nan
    z[~np.isfinite(z)] = np.nan

    return z


def depthColormap():
    """The ramp the DEM is drawn with on screen, so the report matches the app."""

    table = genutils.depthRampLookupTable()

    return ListedColormap(np.asarray(table, dtype=np.float32) / 255.0)


def scopeMask(image, working_area, angle):
    """
    Which pixels of the map this report is about, at a reduced resolution.

    Returns (mask, factor, full_width, full_height). The mask is True where the ortho
    carries data and, when a working area is set, inside it as well.
    """

    channel = image.getRGBChannel()
    mask, full_w, full_h = RasterOps.readValidityMask(channel.filename, shrink=False)

    factor_y = full_h / float(mask.shape[0])
    factor_x = full_w / float(mask.shape[1])

    if working_area is not None:
        rows, cols = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
        # sample at the centre of each reduced cell, in full-resolution coordinates
        xs = (cols + 0.5) * factor_x
        ys = (rows + 0.5) * factor_y
        inside = genutils.workingAreaContains(working_area, angle, xs, ys)
        mask = mask & inside

    return mask, (factor_x, factor_y), full_w, full_h


def plotArea(image, working_area=None, angle=0.0):
    """
    The ground the survey actually covers, in square metres.

    Counted from the pixels that carry data rather than from the size of the raster: an
    orthomosaic is a rectangle with a survey-shaped hole in the middle of it, and the
    rectangle is not the plot.
    """

    mask, (factor_x, factor_y), full_w, full_h = scopeMask(image, working_area, angle)

    px_m = image.pixelSize() / 1000.0
    # each cell of the reduced mask stands for this many full-resolution pixels
    per_cell = factor_x * factor_y

    valid_px = float(mask.sum()) * per_cell
    total_px = float(full_w) * float(full_h)

    return {
        "area_m2": valid_px * px_m * px_m,
        "valid_pixels": valid_px,
        "total_pixels": total_px,
        "fraction": (valid_px / total_px) if total_px else 0.0,
        "px_size_mm": image.pixelSize(),
    }


def orthoSummary(image, working_area=None, angle=0.0):
    """Everything the overview section says about the orthomosaic."""

    channel = image.getRGBChannel()
    info = {"name": image.name, "date": image.acquisition_date, "filename": None}

    if channel is None:
        return info

    info["filename"] = channel.filename
    with rio.open(channel.filename) as src:
        info["width"] = src.width
        info["height"] = src.height
        info["bands"] = src.count
        info["dtype"] = src.dtypes[0]
        info["crs"] = str(src.crs) if src.crs else None
        info["compression"] = src.tags(ns="IMAGE_STRUCTURE").get("COMPRESSION", "none")

    info.update(plotArea(image, working_area, angle))

    return info


def demSummary(image):
    """Everything the overview section says about the DEM, or None when there is none."""

    channel = image.getDEMChannel()
    if channel is None:
        return None

    with rio.open(channel.filename) as src:
        width, height, nodata = src.width, src.height, src.nodata
        crs = str(src.crs) if src.crs else None
        factor = _previewFactor(width, height, 2000)
        # a scalar band index already returns a 2D array, so out_shape is 2D too; asking
        # for a 3D shape and taking [0] read the first row of the DEM instead of the
        # first band, and a survey whose top row is all nodata looked like an empty DEM
        z = src.read(1, out_shape=(max(1, height // factor), max(1, width // factor)))

    z = z.astype(np.float32)
    if nodata is not None:
        z[z == nodata] = np.nan
    z[~np.isfinite(z)] = np.nan

    finite = np.isfinite(z)
    if not finite.any():
        return {"filename": channel.filename, "width": width, "height": height, "empty": True}

    values = z[finite]
    lo, hi = np.percentile(values, (2.0, 98.0))

    return {
        "filename": channel.filename,
        "width": width,
        "height": height,
        "crs": crs,
        "empty": False,
        "coverage": float(finite.mean()),
        "min": float(values.min()),
        "max": float(values.max()),
        "mean": float(values.mean()),
        "p2": float(lo),
        "p98": float(hi),
        "relief": float(hi - lo),
    }


def griddedRugosity(image, cell_size_m=DEFAULT_CELL_SIZE_M, working_area=None, angle=0.0):
    """
    Surface area divided by footprint, over a grid of square cells.

    The same quantity ReefShape computes from the mesh, with the same convention: the
    3D area falling in a cell, divided by the cell's own footprint. The difference is
    that this reads a height field, so it sees one surface per location. An overhang
    contributes twice to the mesh and once here, and a cave not at all, so these numbers
    sit below the mesh ones wherever the reef is not a simple surface. They are
    comparable with each other, not with Metashape.

    Returns (grid, stats) or (None, None) when there is no DEM to work from.
    """

    dem_channel = image.getDEMChannel()
    rgb_channel = image.getRGBChannel()
    if dem_channel is None or rgb_channel is None:
        return None, None

    with rio.open(rgb_channel.filename) as ortho, rio.open(dem_channel.filename) as dem:
        affine, px_mm_x, px_mm_y = RasterOps.demToOrthoMapping(ortho, dem, image.pixelSize())
        z = dem.read(1).astype(np.float32)
        nodata = dem.nodata

    ratio = RasterOps.demCellAreaRatio(z, px_mm_x, px_mm_y, nodata)

    # a DEM cell sits between its four corners, so it is half a pixel in from each
    cell_m_x = px_mm_x / 1000.0
    cell_m_y = px_mm_y / 1000.0
    planar_cell_m2 = cell_m_x * cell_m_y

    rows, cols = ratio.shape
    gy, gx = np.mgrid[0:rows, 0:cols]

    # DEM pixel -> ortho pixel -> metres, so the grid lines up with the map
    inverse = ~affine
    ortho_x = inverse.a * (gx + 0.5) + inverse.b * (gy + 0.5) + inverse.c
    ortho_y = inverse.d * (gx + 0.5) + inverse.e * (gy + 0.5) + inverse.f

    usable = np.isfinite(ratio)
    if working_area is not None:
        usable &= genutils.workingAreaContains(working_area, angle, ortho_x, ortho_y)

    if not usable.any():
        return None, None

    px_m = image.pixelSize() / 1000.0
    world_x = ortho_x * px_m
    world_y = ortho_y * px_m

    x0 = float(world_x[usable].min())
    y0 = float(world_y[usable].min())
    n_cols = max(1, int(math.ceil((float(world_x[usable].max()) - x0) / cell_size_m)))
    n_rows = max(1, int(math.ceil((float(world_y[usable].max()) - y0) / cell_size_m)))

    col_of = np.clip(((world_x - x0) / cell_size_m).astype(np.int64), 0, n_cols - 1)
    row_of = np.clip(((world_y - y0) / cell_size_m).astype(np.int64), 0, n_rows - 1)
    flat = (row_of * n_cols + col_of)[usable]

    surface = (ratio[usable] * planar_cell_m2).astype(np.float64)
    area_3d = np.bincount(flat, weights=surface, minlength=n_rows * n_cols)
    footprint = np.bincount(flat, weights=np.full(flat.shape, planar_cell_m2),
                            minlength=n_rows * n_cols)

    cell_m2 = cell_size_m * cell_size_m
    coverage = footprint / cell_m2

    grid = np.full(n_rows * n_cols, np.nan, dtype=np.float32)
    complete = coverage >= MIN_CELL_COVERAGE
    # Divided by the footprint actually sampled rather than by the nominal cell area. A
    # 1 m cell receives a whole number of DEM cells and they rarely tile it exactly, so
    # dividing by the nominal area makes every cell report slightly low - flat ground
    # came out at 0.9964 instead of 1. Where coverage is complete the two agree.
    grid[complete] = area_3d[complete] / footprint[complete]
    grid = grid.reshape(n_rows, n_cols)

    values = grid[np.isfinite(grid)]
    if values.size == 0:
        return None, None

    stats = {
        "cell_size_m": cell_size_m,
        "n_cells": int(values.size),
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "min": float(values.min()),
        "max": float(values.max()),
        "std": float(values.std()),
        # the plot as one cell: all the surface over all the footprint
        "global": float(area_3d[complete].sum() / footprint[complete].sum()),
        "surface_area_m2": float(area_3d[complete].sum()),
        "partial_cells": int((~complete & (coverage > 0)).sum()),
        "origin": (x0, y0),
    }

    return grid, stats


def pointStats(image, project, working_area=None, angle=0.0, group_classes=None,
               group_label="Selected classes"):
    """
    Counts, proportions and confidence intervals for the annotated points.

    group_classes names the classes that are rolled up into one figure - the live coral
    among the benthos, say. Left empty, no roll-up is reported.
    """

    points = image.annotations.annpoints
    if working_area is not None:
        points = [p for p in points
                  if genutils.workingAreaContains(working_area, angle, p.coordx, p.coordy)]

    total = len(points)
    counts = {}
    for p in points:
        counts[p.class_name] = counts.get(p.class_name, 0) + 1

    rows = []
    for name in sorted(counts, key=lambda k: -counts[k]):
        n = counts[name]
        low, high = wilsonInterval(n, total)
        rows.append({
            "class_name": name,
            "count": n,
            "fraction": n / float(total) if total else 0.0,
            "ci": (low, high),
            "colour": labelColour(project, name),
        })

    group = None
    chosen = [r for r in rows if group_classes and r["class_name"] in group_classes]
    if chosen:
        n = sum(r["count"] for r in chosen)
        low, high = wilsonInterval(n, total)
        within = []
        for r in chosen:
            wl, wh = wilsonInterval(r["count"], n)
            within.append({**r, "fraction_of_group": r["count"] / float(n) if n else 0.0,
                           "ci_of_group": (wl, wh)})
        group = {
            "label": group_label,
            "count": n,
            "fraction": n / float(total) if total else 0.0,
            "ci": (low, high),
            "members": sorted(within, key=lambda r: -r["count"]),
        }

    return {"total": total, "rows": rows, "group": group, "points": points}


def regionStats(image, project, working_area=None, angle=0.0, plot_area_m2=None):
    """
    Counts, areas and cover for the annotated regions.

    Cover is against the surveyed ground rather than the bounding rectangle, which is
    what plot_area_m2 carries; without it the percentages are left out.
    """

    if working_area is not None:
        blobs = image.annotations.calculate_inner_blobs(working_area, angle)
    else:
        blobs = list(image.annotations.seg_blobs)

    scale = image.pixelSize()
    to_m2 = (scale / 1000.0) ** 2

    by_class = {}
    for blob in blobs:
        entry = by_class.setdefault(blob.class_name, {"count": 0, "area_m2": 0.0,
                                                      "surface_m2": 0.0, "sizes": [],
                                                      "with_surface": 0})
        area = blob.area * to_m2
        entry["count"] += 1
        entry["area_m2"] += area
        entry["sizes"].append(area)
        if getattr(blob, "surface_area", 0.0) > 0.0:
            entry["surface_m2"] += blob.surface_area * to_m2
            entry["with_surface"] += 1

    rows = []
    for name in sorted(by_class, key=lambda k: -by_class[k]["area_m2"]):
        e = by_class[name]
        sizes = np.asarray(e["sizes"], dtype=np.float64)
        rows.append({
            "class_name": name,
            "count": e["count"],
            "area_m2": e["area_m2"],
            "cover": (e["area_m2"] / plot_area_m2) if plot_area_m2 else None,
            "mean_m2": float(sizes.mean()),
            "median_m2": float(np.median(sizes)),
            "max_m2": float(sizes.max()),
            "surface_m2": e["surface_m2"] if e["with_surface"] else None,
            "with_surface": e["with_surface"],
            "colour": labelColour(project, name),
        })

    groups = set(b.group for b in blobs if getattr(b, "group", None) is not None)

    return {
        "rows": rows,
        "blobs": blobs,
        "total_count": len(blobs),
        "total_area_m2": sum(r["area_m2"] for r in rows),
        "n_groups": len(groups),
        "n_grouped_regions": sum(1 for b in blobs if getattr(b, "group", None) is not None),
    }


# ---------------------------------------------------------------- rendering


def _style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(RULE)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.yaxis.label.set_color(MUTED)
    ax.xaxis.label.set_color(MUTED)


def _panel(ax, letter, title):
    ax.set_title("%s  %s" % (letter, title), loc="left", fontsize=10.5,
                 fontweight="bold", color=INK, pad=8)


def _frame(ax):
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color(RULE)


def _newPage(title, subtitle=None):
    fig = Figure(figsize=PAGE_SIZE, dpi=200)
    fig.patch.set_facecolor("white")
    fig.text(0.04, 0.955, title, fontsize=15, fontweight="bold", color=INK)
    if subtitle:
        fig.text(0.04, 0.925, subtitle, fontsize=9, color=MUTED)
    fig.add_artist(Line2D([0.04, 0.96], [0.912, 0.912], transform=fig.transFigure,
                          color=RULE, linewidth=0.8))
    return fig


def _footer(fig, text):
    # wrapped here rather than left to matplotlib, whose wrap does not know the figure
    # margins and lets a long note run off the right edge of the page
    fig.text(0.04, 0.045, textwrap.fill(text, 150), fontsize=7, color=MUTED, va="top")


def _textBlock(ax, pairs, title=None):
    """A column of label and value lines, for the figures that are not plots."""

    ax.axis("off")
    y = 1.0
    if title:
        ax.text(0, y, title, fontsize=10.5, fontweight="bold", color=INK,
                transform=ax.transAxes, va="top")
        y -= 0.11
    for key, value in pairs:
        if value is None:
            continue
        ax.text(0.0, y, key, fontsize=8.5, color=MUTED, transform=ax.transAxes, va="top")
        ax.text(0.54, y, str(value), fontsize=8.5, color=INK, transform=ax.transAxes,
                va="top")
        y -= 0.082


def _drawWorkingArea(ax, working_area, angle, scale=1.0):
    if working_area is None:
        return
    corners = genutils.workingAreaCorners(working_area, angle)
    pts = [(x * scale, y * scale) for x, y in corners]
    ax.add_patch(MplPolygon(pts, closed=True, fill=False, edgecolor="#c0392b",
                            linewidth=1.0, linestyle="--"))


def _barsWithCI(ax, names, fractions, intervals, colours, counts, xlabel):
    y = np.arange(len(names))[::-1]
    pct = [100.0 * f for f in fractions]
    lo = [max(0.0, 100.0 * f - 100.0 * i[0]) for f, i in zip(fractions, intervals)]
    hi = [max(0.0, 100.0 * i[1] - 100.0 * f) for f, i in zip(fractions, intervals)]

    ax.barh(y, pct, color=colours, height=0.62,
            xerr=[lo, hi], error_kw={"ecolor": INK, "elinewidth": 0.9, "capsize": 3})
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9, color=INK)
    ax.set_xlabel(xlabel, fontsize=8.5)
    _style(ax)

    # room for the value labels, but a percentage axis should not imply more than
    # everything: a 94% bar was otherwise given an axis running past 130%
    span = max(pct + [1.0])
    ax.set_xlim(0, min(span * 1.45, 118.0))
    for yi, p, n, h in zip(y, pct, counts, hi):
        ax.text(p + h + span * 0.03, yi, "%.1f%%  (n=%d)" % (p, n),
                va="center", fontsize=8.5, color=INK)


def overviewPage(pdf, image, ortho, dem, working_area, angle):
    fig = _newPage("Survey overview",
                   "%s   ·   %s" % (image.name, image.acquisition_date or "no date"))

    ax = fig.add_axes([0.05, 0.44, 0.40, 0.42])
    _panel(ax, "A", "Orthomosaic")
    if ortho.get("filename"):
        ax.imshow(readPreview(ortho["filename"]))
        _drawWorkingArea(ax, working_area, angle,
                         scale=1.0 / _previewFactor(ortho["width"], ortho["height"]))
    _frame(ax)

    px = ortho.get("px_size_mm", 0.0)
    ax = fig.add_axes([0.05, 0.08, 0.40, 0.30])
    _textBlock(ax, [
        ("Dimensions", "%d x %d px" % (ortho.get("width", 0), ortho.get("height", 0))),
        ("Ground sample distance", "%.2f mm/px" % px),
        ("Extent", "%.1f x %.1f m" % (ortho.get("width", 0) * px / 1000.0,
                                      ortho.get("height", 0) * px / 1000.0)),
        ("Plot area (data only)", "%.2f m²" % ortho.get("area_m2", 0.0)),
        ("Data coverage of raster", "%.1f%%" % (100.0 * ortho.get("fraction", 0.0))),
        ("Coordinate system", ortho.get("crs") or "none (pixel coordinates)"),
        ("Stored as", "%s, %s" % (ortho.get("dtype", "?"),
                                  ortho.get("compression", "none"))),
    ])

    ax = fig.add_axes([0.55, 0.44, 0.40, 0.42])
    _panel(ax, "B", "Digital elevation model")
    if dem and not dem.get("empty"):
        z = readDemPreview(dem["filename"])
        im = ax.imshow(z, cmap=depthColormap(), vmin=dem["p2"], vmax=dem["p98"])
        bar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
        bar.set_label("elevation (m)", fontsize=8, color=MUTED)
        bar.ax.tick_params(labelsize=7, colors=MUTED)
    else:
        ax.text(0.5, 0.5, "no DEM in this map", ha="center", va="center",
                fontsize=10, color=MUTED, transform=ax.transAxes)
    _frame(ax)

    ax = fig.add_axes([0.55, 0.08, 0.40, 0.30])
    if dem and not dem.get("empty"):
        dem_px = px * ortho.get("width", 1) / float(dem["width"]) if ortho.get("width") else px
        _textBlock(ax, [
            ("Dimensions", "%d x %d px" % (dem["width"], dem["height"])),
            ("Ground sample distance", "%.2f mm/px" % dem_px),
            ("Elevation range", "%.3f to %.3f m" % (dem["min"], dem["max"])),
            ("Relief (2nd to 98th pct)", "%.3f m" % dem["relief"]),
            ("Mean elevation", "%.3f m" % dem["mean"]),
            ("Valid coverage", "%.1f%%" % (100.0 * dem["coverage"])),
            ("Coordinate system", dem.get("crs") or "none"),
        ])
    else:
        _textBlock(ax, [("DEM", "none in this map")])

    if working_area is not None:
        _footer(fig, "The dashed outline is the working area. Every figure in this report "
                     "is measured inside it.")

    pdf.savefig(fig)


def rugosityPage(pdf, grid, stats):
    cell = stats["cell_size_m"]
    fig = _newPage("Rugosity",
                   "surface area over footprint, on a %.2g m grid" % cell)

    ax = fig.add_axes([0.05, 0.16, 0.42, 0.68])
    _panel(ax, "A", "Rugosity by cell")
    masked = np.ma.masked_invalid(grid)
    cmap = depthColormap()
    cmap = cmap.copy()
    cmap.set_bad("white")
    # stretched over the range present rather than anchored at 1, so that the variation
    # across a plot is visible; a reef sitting between 1.10 and 1.12 was otherwise one
    # flat colour at the top of the ramp
    low = float(np.nanpercentile(grid, 2))
    top = float(np.nanpercentile(grid, 98))
    if top - low < 1e-6:
        low, top = low - 0.01, top + 0.01
    im = ax.imshow(masked, cmap=cmap, vmin=low, vmax=top)
    bar = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    bar.set_label("3D / 2D", fontsize=8, color=MUTED)
    bar.ax.tick_params(labelsize=7, colors=MUTED)
    _frame(ax)

    ax = fig.add_axes([0.57, 0.48, 0.38, 0.36])
    _panel(ax, "B", "Distribution")
    values = grid[np.isfinite(grid)]
    ax.hist(values, bins=int(min(40, max(8, values.size // 4))), color=ACCENT, alpha=0.85)
    ax.axvline(stats["mean"], color="#c0392b", linewidth=1.2,
               label="mean %.3f" % stats["mean"])
    ax.axvline(stats["median"], color=INK, linewidth=1.0, linestyle="--",
               label="median %.3f" % stats["median"])
    ax.set_xlabel("rugosity", fontsize=8.5)
    ax.set_ylabel("cells", fontsize=8.5)
    ax.legend(fontsize=8, frameon=False)
    _style(ax)

    ax = fig.add_axes([0.57, 0.10, 0.38, 0.30])
    _textBlock(ax, [
        ("Cells measured", "%d at %.2g m" % (stats["n_cells"], cell)),
        ("Mean", "%.4f" % stats["mean"]),
        ("Median", "%.4f" % stats["median"]),
        ("Minimum", "%.4f" % stats["min"]),
        ("Maximum", "%.4f" % stats["max"]),
        ("Standard deviation", "%.4f" % stats["std"]),
        ("Whole plot (total 3D / total 2D)", "%.4f" % stats["global"]),
        ("Surface area measured", "%.2f m²" % stats["surface_area_m2"]),
    ], title="Summary")

    _footer(fig, "Measured from the height field, so one surface per location: an overhang "
                 "counts once and a cave not at all. These numbers therefore sit below "
                 "mesh-derived rugosity such as Metashape's, and are comparable with each "
                 "other rather than with it. Cells less than %d%% covered are left out "
                 "(%d of them here), so that every cell reported describes a full one."
            % (int(MIN_CELL_COVERAGE * 100), stats["partial_cells"]))

    pdf.savefig(fig)


def pointsPage(pdf, image, stats, working_area, angle):
    total = stats["total"]
    rows = stats["rows"]
    fig = _newPage("Point counts", "%s   ·   %d points" % (image.name, total))

    ax = fig.add_axes([0.08, 0.56, 0.38, 0.28])
    _panel(ax, "A", "Benthic cover, all points (N=%d)" % total)
    if rows:
        _barsWithCI(ax, [r["class_name"] for r in rows], [r["fraction"] for r in rows],
                    [r["ci"] for r in rows], [r["colour"] for r in rows],
                    [r["count"] for r in rows], "% of points (95% Wilson CI)")
        group = stats["group"]
        if group:
            ax.text(0.98, 0.05, "%s: %.1f%%  (95%% CI %.1f to %.1f%%)"
                    % (group["label"], 100.0 * group["fraction"],
                       100.0 * group["ci"][0], 100.0 * group["ci"][1]),
                    transform=ax.transAxes, ha="right", fontsize=8.5,
                    style="italic", color=INK)
    else:
        ax.axis("off")
        ax.text(0.5, 0.5, "no points in scope", ha="center", color=MUTED,
                transform=ax.transAxes)

    ax = fig.add_axes([0.08, 0.10, 0.38, 0.30])
    group = stats["group"]
    if group and group["members"]:
        _panel(ax, "B", "Relative composition of %s (n=%d)"
               % (group["label"].lower(), group["count"]))
        members = group["members"]
        _barsWithCI(ax, [r["class_name"] for r in members],
                    [r["fraction_of_group"] for r in members],
                    [r["ci_of_group"] for r in members],
                    [r["colour"] for r in members], [r["count"] for r in members],
                    "%% of %s points (95%% Wilson CI)" % group["label"].lower())
    else:
        ax.axis("off")
        ax.text(0.0, 0.92, "B  Relative composition", fontsize=10.5, fontweight="bold",
                color=INK, transform=ax.transAxes)
        ax.text(0.0, 0.78, "No classes were chosen to roll up, so there is no\n"
                           "composition to break down.",
                fontsize=8.5, color=MUTED, transform=ax.transAxes, va="top")

    ax = fig.add_axes([0.54, 0.14, 0.42, 0.70])
    _panel(ax, "C", "Point locations (map pixels)")
    by_class = {}
    for p in stats["points"]:
        by_class.setdefault(p.class_name, []).append((p.coordx, p.coordy))
    for r in rows:
        pts = by_class.get(r["class_name"], [])
        if not pts:
            continue
        dominant = len(pts) > 0.5 * max(1, total)
        ax.scatter([p[0] for p in pts], [p[1] for p in pts],
                   s=3 if dominant else 16, c=[r["colour"]],
                   alpha=0.45 if dominant else 0.95, linewidths=0,
                   label="%s (%d)" % (r["class_name"], len(pts)))
    ax.set_aspect("equal")
    ax.invert_yaxis()
    _drawWorkingArea(ax, working_area, angle)
    _frame(ax)
    if rows:
        ax.legend(fontsize=8, frameon=False, loc="upper center",
                  bbox_to_anchor=(0.5, -0.01), ncol=2)

    pdf.savefig(fig)


def regionsPage(pdf, image, stats, plot_area_m2, working_area, angle):
    rows = stats["rows"]
    fig = _newPage("Regions", "%s   ·   %d regions" % (image.name,
                                                            stats["total_count"]))

    ax = fig.add_axes([0.06, 0.52, 0.40, 0.32])
    _panel(ax, "A", "Cover by class")
    if rows and plot_area_m2:
        y = np.arange(len(rows))[::-1]
        pct = [100.0 * r["cover"] for r in rows]
        ax.barh(y, pct, color=[r["colour"] for r in rows], height=0.62)
        ax.set_yticks(y)
        ax.set_yticklabels([r["class_name"] for r in rows], fontsize=9, color=INK)
        ax.set_xlabel("%% of plot area (%.2f m²)" % plot_area_m2, fontsize=8.5)
        span = max(pct + [0.5])
        ax.set_xlim(0, span * 1.5)
        for yi, p, r in zip(y, pct, rows):
            ax.text(p + span * 0.03, yi, "%.2f%%  (%d)" % (p, r["count"]),
                    va="center", fontsize=8.5, color=INK)
        _style(ax)
    else:
        ax.axis("off")
        ax.text(0.5, 0.5, "no regions in scope" if not rows else "plot area unknown",
                ha="center", color=MUTED, transform=ax.transAxes)

    ax = fig.add_axes([0.06, 0.10, 0.40, 0.30])
    _panel(ax, "B", "Region size distribution")
    sizes = np.asarray([b.area * (image.pixelSize() / 1000.0) ** 2
                        for b in stats["blobs"]], dtype=np.float64)
    positive = sizes[sizes > 0] if sizes.size else sizes
    if positive.size:
        ax.hist(positive, bins=int(min(30, max(6, positive.size // 3))),
                color=ACCENT, alpha=0.85)
        ax.axvline(float(np.median(positive)), color="#c0392b", linewidth=1.2,
                   label="median %.4f m²" % float(np.median(positive)))
        ax.legend(fontsize=8, frameon=False)
        ax.set_xlabel("region area (m²)", fontsize=8.5)
        ax.set_ylabel("regions", fontsize=8.5)
        _style(ax)
    else:
        ax.axis("off")
        ax.text(0.5, 0.5, "no regions in scope", ha="center", color=MUTED,
                transform=ax.transAxes)

    ax = fig.add_axes([0.54, 0.46, 0.42, 0.38])
    _panel(ax, "C", "Per class")
    ax.axis("off")
    header = ["Class", "n", "Area m²", "Cover", "Mean m²", "Surface m²"]
    xs = np.cumsum([0.0, 0.30, 0.09, 0.16, 0.12, 0.16])
    for x, h in zip(xs, header):
        ax.text(x, 0.95, h, fontsize=8, color=MUTED, transform=ax.transAxes,
                fontweight="bold")
    y = 0.87
    for r in rows[:12]:
        cells = [r["class_name"][:18], str(r["count"]), "%.3f" % r["area_m2"],
                 ("%.2f%%" % (100.0 * r["cover"])) if r["cover"] is not None else "-",
                 "%.4f" % r["mean_m2"],
                 ("%.3f" % r["surface_m2"]) if r["surface_m2"] else "-"]
        for x, c in zip(xs, cells):
            ax.text(x, y, c, fontsize=8, color=INK, transform=ax.transAxes)
        y -= 0.068
    if len(rows) > 12:
        ax.text(0, y, "and %d more classes" % (len(rows) - 12), fontsize=8,
                color=MUTED, transform=ax.transAxes, style="italic")

    ax = fig.add_axes([0.54, 0.09, 0.42, 0.30])
    pairs = [
        ("Regions", "%d" % stats["total_count"]),
        ("Total region area", "%.3f m²" % stats["total_area_m2"]),
        ("Plot area", ("%.2f m²" % plot_area_m2) if plot_area_m2 else None),
        ("Total cover", ("%.2f%%" % (100.0 * stats["total_area_m2"] / plot_area_m2))
         if plot_area_m2 else None),
    ]
    if stats["n_groups"]:
        pairs.append(("Colonies grouped from pieces",
                      "%d groups over %d regions" % (stats["n_groups"],
                                                     stats["n_grouped_regions"])))
    _textBlock(ax, pairs, title="Totals")

    if any(r["surface_m2"] for r in rows):
        _footer(fig, "Surface area is reported only for regions it has been calculated "
                     "for, and is a 2.5D measure from the DEM.")

    pdf.savefig(fig)


def writeReport(filename, project, image, sections=None, cell_size_m=DEFAULT_CELL_SIZE_M,
                group_classes=None, group_label="Live coral", use_working_area=True,
                progress=None):
    """
    Write the report. Returns the list of sections actually included.

    sections names what to put in: overview, rugosity, points, regions. A section with
    nothing to say about this map is dropped rather than printed empty, and the names
    that survive come back so the caller can say what was written.
    """

    wanted = set(sections or ("overview", "rugosity", "points", "regions"))

    working_area = None
    angle = 0.0
    if use_working_area and getattr(project, "working_area", None):
        working_area = project.working_area
        angle = getattr(project, "working_area_angle", 0.0)

    def step(text, fraction):
        if progress:
            progress(text, fraction)

    step("Measuring the orthomosaic...", 0.05)
    ortho = orthoSummary(image, working_area, angle)
    dem = demSummary(image)
    written = []

    with PdfPages(filename) as pdf:
        if "overview" in wanted:
            step("Drawing the overview...", 0.2)
            overviewPage(pdf, image, ortho, dem, working_area, angle)
            written.append("overview")

        if "rugosity" in wanted and dem and not dem.get("empty"):
            step("Computing rugosity...", 0.4)
            grid, stats = griddedRugosity(image, cell_size_m, working_area, angle)
            if grid is not None:
                step("Drawing rugosity...", 0.6)
                rugosityPage(pdf, grid, stats)
                written.append("rugosity")

        if "points" in wanted and image.annotations.annpoints:
            step("Summarising points...", 0.75)
            stats = pointStats(image, project, working_area, angle,
                               group_classes, group_label)
            if stats["total"] > 0:
                pointsPage(pdf, image, stats, working_area, angle)
                written.append("points")

        if "regions" in wanted and image.annotations.seg_blobs:
            step("Summarising regions...", 0.9)
            stats = regionStats(image, project, working_area, angle,
                                ortho.get("area_m2"))
            if stats["total_count"] > 0:
                regionsPage(pdf, image, stats, ortho.get("area_m2"),
                            working_area, angle)
                written.append("regions")

        info = pdf.infodict()
        info["Title"] = "TagLab statistics - %s" % image.name
        info["Creator"] = "TagLab"
        info["CreationDate"] = datetime.now()

    # A pdf with no pages in it is not a pdf a reader will open - it comes out as a few
    # hundred bytes with no page tree. That happens when every section asked for turns
    # out to have nothing to report, so take the file away again rather than leave
    # something broken behind with a cheerful message about it.
    if not written:
        try:
            os.remove(filename)
        except OSError:
            pass

    step("Done.", 1.0)

    return written
