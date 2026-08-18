# TagLab — Perry Institute fork: changes for upstream review

Thirty-one commits made while annotating coral reef photomosaics at the Perry Institute for
Marine Science. Most are fixes and limit removals that are not specific to our workflow; a few are
ours alone. This document sorts them so you can tell which is which.

| | |
|---|---|
| **Forked at** | `0150d84`, 20 May 2026 — "first working version of the georeferencing tool" |
| **Commits** | 31, plus this document (nothing of upstream `main` is missing from this fork) |
| **Diff** | +3769 / −567 across 31 files |
| **New dependencies** | none — `requirements.txt` and `install.py` untouched |
| **Repo** | `https://github.com/wogreene/TagLab`, branch `main` |

Each entry is labelled:

- **ADOPT** — a defect fix or limit removal with no change in intended behaviour. Should apply cleanly.
- **DISCUSS** — sound, but changes numbers, semantics, or a default. Needs your call.
- **FORK ONLY** — specific to how we distribute this build. Listed for completeness; do not merge.

---

## At a glance

| Change | Status | Commit |
|---|---|---|
| Surface area returned planar area | DISCUSS | `73bb9f5` |
| DEM at its own resolution | ADOPT | `73bb9f5` |
| Overhang clipping in surface area | DISCUSS | `73bb9f5` |
| 32767 px load limit removed | ADOPT | `fed07dc` |
| Map memory 12.6 → 4.4 bytes/px | ADOPT | `fed07dc` |
| 1-, 2- and 4-band images no longer crash | ADOPT | `fed07dc` |
| GDAL cache cap and memory-mapped decode | ADOPT | `8fa1ba2` |
| Offer a reduced-resolution copy | DISCUSS | `7fcea17` |
| Dataset export at any map size | DISCUSS | `7500ef7` |
| Clicks tool work area sized to hardware | ADOPT | `a40c4b9` |
| CPU-path limits for machines without CUDA | ADOPT | `1174ab6` |
| Whole-map point sampling excluding nodata | ADOPT | `99af0da` |
| Randomly placed, randomly angled working area | DISCUSS | `0cd7cd0` |
| Merging separated regions produced a broken one | ADOPT | `d49bd16` |
| Grouping pieces of one colony | DISCUSS | `d9e15c4` |
| Data panel formatted by position, not by name | ADOPT | `5fd62a2` |
| Labels panel column widths | ADOPT | `3b0f277` |
| Labels panel icons undersized and left-aligned | ADOPT | `2fcd8b0` |
| Co-registration ran out of memory on a large map | ADOPT | `131cde8` |
| Co-registered map clipped to the original canvas | ADOPT | `9591444` |
| A coarser DEM moved by the wrong amount | ADOPT | `48071fe` |
| Aligned copies written uncompressed | ADOPT | `27ea9cb` |
| Alignment preview black on a large map | ADOPT | `5ed5d6e` |
| Displaying a DEM cost 52 bytes a pixel | ADOPT | `2f2a759` |
| DEM nodata painted instead of left clear | ADOPT | `3d64843` |
| Keyboard labelling from the data table | ADOPT | `5f2f776` |
| Save prompt only when something changed | ADOPT | `c74d13f` |
| Ask before discarding unsaved work | ADOPT | `ae4379d` |
| DEM drawn as coloured shaded relief | DISCUSS | `a09704b` |
| Console warnings cleared | ADOPT | `79f6ce2`, `b9d3a76` |
| Manual corrected on export size | ADOPT | `e7c3703` |
| Forced-update lockout disabled | FORK ONLY | `fed07dc` |
| `update.py` rewritten | FORK ONLY | `a1a567e`, `dca9556` |

---

## Measurement

### Surface area has been reporting the planar area — DISCUSS (`73bb9f5`)

**Upstream:** `gdal.DEMProcessing` derives a slope raster, and the filter `slope[slope > 87] = 0`
discards near-vertical cells.

On a DEM in a geographic CRS the horizontal unit is degrees while elevations are metres, so the
derived slope is about 89.999° almost everywhere. The filter then zeroes essentially every pixel,
and `cos(0) = 1`. On a real 9317×9737 reef DEM the mean correction factor came out at exactly
1.000000 — every region reported its planar area.

The slope calculation is replaced by the triangulated area of each DEM cell computed from its four
corner heights. That is the exact area of the interpolated surface, needs no trigonometry, and
stays correct on near-vertical faces. GDAL is no longer involved, and the 363 MB `slope.tif`
written to disk on every calculation is gone.

Validated against known geometry:

| | |
|---|---|
| Ramps at 30°, 45°, 60° | exact |
| Hemispherical cap of known area | −0.7% |

> **This changes published numbers.** Any project whose surface areas were exported before this fix
> holds planar values. After it, the same regions report larger areas. That is a correction, but it
> is not backwards compatible.

### A DEM can keep its own resolution — ADOPT (`73bb9f5`)

**Upstream:** the DEM is assumed to share the orthomosaic's pixel grid.

A 2 mm DEM against a 0.5 mm ortho is a far lighter product than resampling to full resolution, and
where both are georeferenced their geotransforms state exactly how they line up. Composing the two
transforms handles any ratio — verified exact from 1× to 8.759×.

The DEM's pixel size in mm is derived from the ortho's pixel size times that ratio, which is
dimensionless, so projected, geographic and wholly unreferenced rasters all work with no
CRS-specific code. (This matters for collaborators working from unreferenced JPEG imagery in local
coordinates.) Regions are still sampled at ortho resolution and only the area ratio comes from the
DEM, so an outline keeps its full precision instead of being quantised to the DEM cell. A region
not fully covered by valid DEM is left blank rather than given a number derived from a hole.

### Clipping the overhang artefact — DISCUSS (`73bb9f5`)

An outline sometimes catches the lip of an overhang or the edge of a shelf beside the colony. Those
cells are a step between two surfaces, and a few of them can double a region's reported area. They
are separable from genuine steepness by their distribution: they concentrate on the thin line of
the step. Each region's per-pixel factors are clipped at its own 95th percentile.

| Cap with a substrate crevice cut into it | |
|---|---|
| Three crevice cases, before | +67% / +92% / +28% |
| Three crevice cases, after | under 1% |
| Cost to a clean dome | −0.7% |

Regions losing more than a quarter are listed afterwards so the outline can be checked. Erosion was
tried first and made the worst cases worse, since crevices run through regions rather than hugging
their edges.

> **A heuristic with a hard-coded constant.** `SURFACE_OUTLIER_PERCENTILE = 95.0` is a judgement
> call, not a derived value. It is deliberately one-sided in effect: because the factors are built
> from squared gradients, both an overhang above a colony and a dropoff below it produce large
> factors, so clipping the top tail catches both. It is not exposed in the UI. If you adopt this, it
> probably wants to be a setting.

---

## Large maps and memory

Our working orthomosaics run to roughly 60000×60000 px.

### The 32767×32767 limit applies to drawing, not loading — ADOPT (`fed07dc`)

**Upstream:** maps larger than 32767 px on a side are refused at load.

On Qt 5.15 that clamp applies only when *drawing into* an image. Allocating, cropping and displaying
larger maps all work, as does rendering annotations at those coordinates. The practical limit is now
memory. Where the paint clamp genuinely does apply, the code fails loudly instead of emitting black
pixels: `genutils.QT_RASTER_COORD_LIMIT` guards those call sites and surfaces the reason in a
dialog.

Also in this commit: an undecodable map is reported as such, rather than reopening the "couldn't
find the map" file dialog whose filter did not even list `.tif`.

### A loaded map costs 4.4 bytes per pixel, not 12.6 — ADOPT (`fed07dc`)

`Channel.loadRGB` decodes in 1024-row stripes directly into the BGRA buffer QImage expects, rather
than reading the whole `(c,h,w)` array, transposing it, building a second array and copying again.
`QGraphicsBigImageItem` paints straight from the QImage, replacing the `QGraphicsPixmapItem` that
held a second full-resolution copy, and the overlay is its own item instead of being composited into
a copy of the entire map.

The same commit fixes an `UnboundLocalError` on 1-, 2- and 4-band images, and resolves the filename
against the TagLab directory as the DEM channel already did.

| 40000×40000 JPEG/YCbCr GeoTIFF | |
|---|---|
| Load time | ~7 s |
| Resident | 6.6 GB |
| Pixels either side of the old 32767 boundary | correct |

### GDAL cache cap and memory-mapped decode — ADOPT (`8fa1ba2`)

GDAL's block cache defaults to 5% of physical RAM — 3.2 GB on a 64 GB machine — but decoding a map
is one sequential pass in which every block is read exactly once, so a large cache buys nothing and
is charged against the same budget as the image. It is capped at 256 MB, set before `rasterio` is
imported because GDAL reads `GDAL_CACHEMAX` at library init rather than lazily. An explicit value in
the environment still wins.

Images above 512 MB of pixels decode into a memory-mapped scratch file. Anonymous memory must be
covered by RAM or the pagefile; a file-backed mapping need not, so the pages become evictable and
the machine only holds the part of the map being looked at. The scratch file removes itself when its
last handle closes — `O_TEMPORARY` on Windows, unlink-while-open elsewhere — so a crash cannot leave
gigabytes behind, and anything that goes wrong falls back to ordinary memory.

| Abaco orthomosaic, 37268×38950 | Before | After |
|---|---|---|
| Peak | 11.57 GB | 6.53 GB |
| Private commit | 5.41 GB | 0.05 GB |
| Load time | 16 s | 9.8 s |

### Offer a reduced-resolution copy when a map will not fit — DISCUSS (`7fcea17`)

Adding a map estimates what it will cost to hold, at 4 bytes per pixel, against free physical
memory. Where it will not comfortably fit, TagLab offers to work from a copy reduced by a power of
two instead of loading it anyway and thrashing.

The reduction is written as a new raster rather than applied to pixels after loading. That matters:
the copy carries a geotransform matching its own pixels, so shapefile, DXF and SVG export,
georeferenced label maps, DEM alignment and surface area all keep working against it untouched.
Downscaling only the in-memory pixels would have left the seven places in `RasterOps` that convert
pixel to world coordinates silently wrong by the reduction factor. A photogrammetry ortho normally
carries overview pyramids, so GDAL reads the reduction out of one rather than touching
full-resolution data — reducing the Abaco map by 4 took 3 seconds.

Nothing changes on a machine with room to spare: the check returns the original file and no dialog
appears. This is a new user-facing prompt, which is why it is flagged rather than assumed.

---

## Dataset export

### Rasterise class codes directly instead of painting colours and reading them back — DISCUSS (`7500ef7`)

**Upstream:** export builds a full-size RGB image, paints every region in its class colour, converts
to a numpy array, then matches colours to recover an int64 code per pixel. It also refuses to run at
or near full resolution on a large map — the "image to export is too big" message — because
`QImage.scaled()` returns black past 32767.

Regions are now filled straight into a uint8 code array with `cv2.fillPoly`, and each tile is cut
and rescaled from the orthoimage on its own rather than rescaling the whole map. Region ids are no
longer packed into RGB channels and unpacked again in every tile.

| 20000×20000 map | |
|---|---|
| `createLabelImage` | 5.59 GB → 0.37 GB (15× less) |
| Peak working set | 0.54 GB |
| Per-tile rescale vs whole-map | bit-identical at 0.5, 0.667, 1.0 |

> **Region outlines shift by about a pixel.** The new raster agrees with `blob.getMask()`, which is
> how `blob.area` is already measured. On a 120 px radius region the old raster was 608 pixels short
> of the mask; the new one matches exactly. This is the more correct behaviour, but exports will
> differ slightly from previous ones.

---

## Interactive segmentation

### The positive/negative clicks work area is sized to the machine — ADOPT (`a40c4b9`)

**Upstream:** a flat 9 MPixel ceiling on every machine — "the input size is too big".

That constant bore no relation to what the hardware could do: on a 24 GB card a 4096×4096 area
segments at full detail in 0.9 s and was being turned away. The limit is now derived from free
memory in two tiers. Up to what memory allows and no further than stays interactive, the work area
goes through the network untouched, exactly as before. Past that the input is scaled for the network
rather than the area being refused — `LimitLongestSide` resizes the input, moves the clicks with it
and scales the prediction back. The predictor already supported this; TagLab never asked for it.

| Why the interactivity ceiling is needed, not just the memory one | |
|---|---|
| 4096×4096 | 0.9 s |
| 5120×5120 | 18.5 s |
| 6144×6144 | 85.6 s, 41 GB host |
| 8192×8192, scaled path | 0.9 s, 4.5 GB |

Scaling is deliberately not used when the area fits at full resolution: on a real 3072×3072 area the
scaled and unscaled masks agreed on 1% of their pixels, so it is a way to get an answer where there
would otherwise be none, and the tool says so when it happens. Only the first click is affected,
since from the second onwards the predictor crops to the object it has found. Where free memory
cannot be determined, the old flat behaviour is kept.

### Memory is the wrong constraint without a GPU — ADOPT (`1174ab6`)

TagLab only ever looks for CUDA, so every Mac takes the CPU path whatever hardware it has, and there
the scarce resource is time, not memory. A 32 GB Mac has memory for far more than it has patience
for, so the previous commit alone would have let it attempt work areas taking minutes. The
full-resolution limit on CPU is capped at the 9 MPixels this tool has always used, and the scaled
path stops at 150 MPixels and asks for a zoom rather than appearing to hang.

| CPU first-click timings, 24 threads | |
|---|---|
| 1.0 MPixel | 1.2 s |
| 4.2 MPixel | 4.8 s |
| 9.4 MPixel | 12.1 s |
| 67 MPixel, scaled | 4.8 s |
| 151 MPixel, scaled | 8.4 s |

This commit also fixes the free-memory query on macOS, which does not define `SC_AVPHYS_PAGES`. It
was raising, being swallowed, and reporting memory as unknown — silently disabling the
reduced-resolution offer on exactly the machines that need it most.

---

## Sampling and working area

### Point sampling over the whole map, excluding nodata — ADOPT (`99af0da`)

**Upstream:** points can only be placed inside a rectangular sampling area.

When a map has already been exported cropped to a region of interest, drawing a second rectangle
inside it is redundant, and no rectangle fits a region of interest that is not a rectangle. A fourth
mode spreads points over every pixel carrying data. Validity comes from rasterio's `dataset_mask`,
which covers an alpha band, a nodata value and an internal mask alike, and reports everything valid
when the file declares nothing — so a 4-band ortho, a GeoTIFF with a nodata value and a plain JPEG
all work with no special casing.

The mask is read decimated and eroded by one cell, so a point accepted against it is still inside
the surveyed area at full resolution. Cell size is derived from the area carrying data rather than
its bounding box — otherwise asking for 1000 points on a map that is 60% data yields about 600.

| Real ortho, 1000 points requested | |
|---|---|
| Grid / Random / Stratified | 1009 / 1000 / 995 |
| Landing on valid data, scored against an un-eroded mask | 100% |
| Mask read for 37268×38950 | ~1 s |

### A randomly placed, randomly angled working area — DISCUSS (`0cd7cd0`)

A second way to set the working area: give a size in metres and drop it on the map at a random
position and a random angle, the way a transect is laid on a reef. This is the one addition driven
purely by our survey design, so it may not be wanted upstream — but the rotation groundwork
underneath it is reusable.

`Project.working_area` is still `[top, left, width, height]`, with a new `working_area_angle`
turning it about its own centre. Zero — and any project saved before the field existed — means the
rectangle it has always been, so old projects load unchanged. What is inside the area is decided
exactly rather than by the enclosing box: `workingAreaContains` rotates the point into the area's
own frame, and the region and point filters use it.

> **One boundary worth knowing.** Operations that must cut a rectangle out of a raster —
> classification, label map and CoralNet export — use the enclosing box and so cover slightly more
> than the rotated area. Region and point counts, which the reported numbers rest on, are exact.
> Making the raster crops rotation-aware is separate work we have not done.

---

## Regions and colonies

### Merging separated regions produced a broken region — ADOPT (`d49bd16`)

**Upstream:** `Annotation.union` paints the selected masks into one array and rebuilds a blob from
it. It returns `None` only when that mask is entirely empty, so the `"blobs are separated"` branch
below it cannot be reached — and it has no message attached in any case.

The merge does not refuse separated regions. It accepts them and corrupts the result. A blob
carries a single outer contour, so `createContourFromMask` keeps whichever piece has the largest
bounding box and files the rest as *inner* contours — holes lying outside the contour they are
holes in. The area is measured from the mask and so counts every piece, leaving a region whose
stated area is larger than the geometry anyone reads back.

| Merging a 60×60 and a 40×40 region 300 px apart | |
|---|---|
| Reported area | 5200 |
| Area enclosed by the contour | 3600 |
| Bounding box | covers only the first piece |
| Centroid | open water, between the two |
| With three pieces | 22% of the region missing from the geometry, area still whole |

`union` now returns `None` when the painted mask is more than one connected piece, and says so.

Connectivity is edge-wise rather than corner-wise. Two regions meeting at a single corner are one
piece by the looser rule, but the contour tracer still walks them as two rings — allowing them
reproduced exactly the same broken result, measured, before settling on the stricter rule.
Overlapping regions, regions sharing an edge and runs of several touching regions all still merge,
and a region with a hole keeps it: the two halves of a holed square merge to area 3200, contour
mask 3200, one inner contour.

This one is worth taking regardless of anything else here.

### Grouping pieces of one colony — DISCUSS (`d9e15c4`)

A colony often branches or buds into pieces that do not touch, and each piece is its own region
with no way to say they are one coral. Across timepoints the genet covers this, being the connected
components of the correspondence graph; a single-timepoint project has no correspondences, so every
region stands alone.

Group is the missing half of that same idea rather than a second one. `Blob.group` holds a key
shared by pieces of one colony within a map, and `updateGenets` seeds its union-find with those
links alongside the correspondences, so a colony reads as one genet whether its pieces were related
across time or within a single map. Select the pieces and press `G`; `shift+G` takes them out
again.

Three decisions worth your scrutiny:

- **The link is saved, not the genet.** Genet ids are positional — recomputed on load and
  renumbered whenever the set of regions changes. We measured this: deleting one colony from a
  two-timepoint project renumbered 7 of the 9 survivors, and `genet 4` came to mean a different
  colony than it had before. So a genet id cannot carry a grouping.
- **The key is the lowest member id, chosen once and then left alone.** `getFreeId` hands out the
  lowest unused id, so ids are recycled after a deletion; a key that recomputed itself would
  eventually be claimed by an unrelated region that inherited the id. That case is checked for and
  tested.
- **The isolate count is not stored.** It is the number of members a genet has in a map, counted at
  export, so it cannot fall out of step with the regions the way a saved integer would. It appears
  per map in the genet CSV next to the class, id and area already there.

We considered instead making a blob multipart, so that separated pieces could genuinely merge into
one region. We think that is the wrong trade: it would mean reworking the contour representation
and everything reading it, the edit tools would collapse a multipart region back to one piece on
the next edit, and it destroys the per-piece areas that a colony-level analysis can always derive
but never recover.

Pieces of one colony cannot be two species, so grouping settles the class. Unclassed pieces take
the class of the classed ones with no prompt; where genuinely different classes meet, the choice is
put to the user, restricted to the classes actually present, and cancelling changes nothing.

> **Note the keybinding.** `G` toggled the grid; that moves to `Ctrl+G`. And `Blob.group` is a new
> saved field — absent in older projects, which read as ungrouped, but projects written by this
> build carry it.

Also in this commit: the genet CSV was written without `newline=''`, putting a blank line after
every row on Windows.

---

## Panels

### The data panel formatted cells by position — ADOPT (`5fd62a2`)

**Upstream:** the table model formats by column index — column 0 is the id, 3 and 4 are
measurements.

Adding a column to that table shifts every column after it into someone else's formatting rule.
Inserting Group at position 1 moved `Class` into a slot that formats floats, and drawing the first
row raised `TypeError: '>' not supported between instances of 'str' and 'int'`. The lookup is now
by column name, so a rule travels with its column.

We hit this because of our own change, but the fragility is upstream's and the next column added
would hit it too.

### The labels panel gave its space to the coverage — ADOPT (`3b0f277`)

The counts and the coverage were sized to their contents, which let them take whatever they asked
for and left the class name whatever remained. In a docked panel that came to 68 px of 469, so
class names read `"Unknow..."` while the coverage had 149 px for a six-digit number.

| Column | Before | After |
|---|---|---|
| Visibility | 25 px | 35 px |
| Class | 68 px | 197 px |
| #R / #P | 66 / 67 px | 49 / 50 px |
| Coverage | 149 px | 102 px |

The heading `"Coverage"` is wider than any figure beneath it and was setting the column width on
its own, so it is displayed as `"Cov."` — the column in the table keeps its name. The three numeric
columns are draggable rather than fixed, so an unusually long figure can still be widened to read
in full. Widths come from the header font rather than being written in pixels, so a different font
size or display scaling moves them together.

### The labels panel icons were undersized and left-aligned — ADOPT (`2fcd8b0`)

Two separate causes, neither of them the column width.

The icon files are mostly empty space: the eye is drawn across 46% of the width of its canvas and
32% of the height, the cross across 26% of each. Scaling the canvas to a given size therefore draws
a mark far smaller than that, and draws the two at visibly different sizes — the cross about half
the eye. Both are now cropped to their opaque bounding box before being scaled, measured from the
alpha channel rather than written down.

The size was a literal 20 px, which is small on a display rendering text at 34 px. It now follows
the header font like the column widths. Together these take the eye from 9 px of visible ink to 20,
and the cross from 5 px to 20, the two now matching.

Centring needs a delegate: `TextAlignmentRole` aligns the text of a cell and not its icon, so both
icons sat against the left edge whatever the alignment said. The delegate lets the style draw the
cell as usual, selection and all, with the icon suppressed, then places the icon in the middle of
it.

Also stops handing back a pixmap with a live `QPainter` still attached to it, which the old drawing
code did on every repaint.

---

## Co-registration

Five defects in the alignment tool, found bringing a second timepoint into a project. All of
them bite harder the larger the map is, which is probably why they have survived.

### It ran out of memory on a large map — ADOPT (`131cde8`)

`Image.__updateChannel` padded the map, shifted it back by the padding, then rotated and
translated it. That is three full-size copies, and the last two are `float64` because that is
what `skimage.warp` returns whatever went in. Four bands at 26165x28364 come to 22.1 GB each,
and the cast back to the map's own dtype only happened at the end, after both had been built.
Confirming an alignment on a 28000 px map died in numpy asking for 22 GB in one allocation.

The two transforms compose into one, so there is now a single resampling rather than two — the
map was being interpolated twice, which blurred it as well as costing the memory. Applying that
single affine a band at a time, into an output of the map's own dtype, holds two bands instead
of the whole map.

| 12000x11000 map, 13600x12900 output | |
|---|---|
| Old, per allocation | 5.2 GB, and it built two |
| New, peak above baseline | 0.70 GB, 4.3 bytes per output pixel |

Verified identical to the code it replaces at rotations from -33 to 180 degrees, with and
without translation and borders. End to end the two differ by at most 1, because the old code
truncated the float back to uint8 where this rounds.

One detail that matters: a band read on its own carries a two pixel margin. Bilinear sampling
just outside the data has to blend with the padding the way it did when the padding was really
there; with nothing to blend against it returns the fill value and eats a pixel off every edge -
94 pixels of 3996 in the case that caught it.

### The co-registered map was clipped to the original canvas — ADOPT (`9591444`)

The borders the new raster is grown by came from the bounding box of the map's **regions** after
transforming them. A map being brought in to be co-registered has no regions on it yet, so that
box starts at 1e9, collapses to a rectangle of negative size, and drives all four borders to
zero. The rotated map is then written into a canvas the size of the original and everything the
rotation swings outside it is lost. Even with regions on it the corners of the map reach further
than they do.

The borders now come from the four corners of the map, transformed the same way, with the
regions kept in the union in case any sit outside it, and rounded outwards.

| 3000x2400 map, rotated 12 degrees and shifted | Borders | Corners kept | Map retained |
|---|---|---|---|
| Regions only, none present | 0, 0, 0, 0 | 2 of 4 | 73.4% |
| Map corners included | 0, 574, 714, 0 | 4 of 4 | 100% |

On a 40000x38000 map at 3 to 25 degrees, one to three corners used to fall outside the canvas.

### A coarser DEM was moved by the wrong amount — ADOPT (`48071fe`)

This one only bites once a DEM is allowed its own resolution, so it pairs with `73bb9f5` above.

The alignment is expressed in ortho pixels - the borders, the translation and the geotransform
stamped on the result all are - and every channel was handed those numbers as they stood. A DEM
four times coarser was therefore moved four times too far, grown by four times too much, and
given the ortho's pixel size. It landed a long way from the map it had just been aligned to, and
the compatibility check refused it with "the DEM only covers 9% of the map" - the check doing its
job on a channel that had been mistransformed.

Each channel is now moved by the same ground rather than the same count of pixels. A channel on
the ortho's own grid spans one and comes out exactly as before. The copy also took its width and
height from whichever channel happened to be last round the loop, so a coarser DEM redefined the
pixel grid the annotations live in; only channels on the ortho's grid set it now.

On a 3000x2400 ortho at 2 mm with a 750x600 DEM at 8 mm: the DEM comes out 894x778 against the
ortho's 3574x3114, the ratio of four it started with, covering 99.9% of the aligned ortho with
origins agreeing to half a DEM pixel.

### Aligned copies were written uncompressed — ADOPT (`27ea9cb`)

Whatever they were made from. On a JPEG-compressed orthomosaic that turns a 41 KB map into a
20 MB one, and a co-registration produces two of them. The source's compression, tiling and
interleave are now carried across; anything the driver will not accept for the data being
written is dropped and the write retried, since JPEG cannot hold a float DEM.

Worth knowing if you adopt this: GDAL reports JPEG with a YCbCr colour space as `YCbCr JPEG`,
which is not a name the writer takes, so the two halves have to be given separately. The
original JPEG quality is not recorded in the file, and the map is resampled and so re-encoded
whatever happens, so 90 is used where nothing says otherwise.

### The preview was black on a large map — ADOPT (`5ed5d6e`)

The preview shown before confirming uploads both maps as OpenGL textures at full resolution. A
map past the card's maximum texture size cannot be uploaded - the texture comes back empty and
there is nothing to sample, so the preview showed black with only the markers drawn over it. The
viewers in the earlier stage of the tool are ordinary raster views and were never affected,
which is why only that window went dark.

The textures now get a copy no larger than 8192 px, and no larger than the limit the card
reports. Nothing else moves: the preview samples in normalised coordinates and is handed the
real map sizes separately. The copy is point-sampled rather than going through `QImage.scaled`,
which on an ARGB32 map converts the whole thing to premultiplied form first.

---

## Displaying a DEM

### It cost 52 bytes a pixel — ADOPT (`2f2a759`)

Against the 8 the result is actually kept in. Everything existed full size and in floating point
at once: a cast copy of the elevations, the two gradients, the surface normal, the shading
before and after `nan_to_num`, the depth index, the coloured image, that image again multiplied
by the shading, and a fourth copy on the way into the QImage.

Rendering into the buffer a band at a time drops it to 11, and is quicker. The bands overlap by
a row so the gradient at a seam is the gradient it would have had in one pass, and the buffer is
the same kind the RGB channel allocates - backed by a scratch file once it is large enough.

| 9000x8000 DEM | Before | After |
|---|---|---|
| Peak | 52.2 B/px | 11.3 B/px |
| Time | 4.3 s | 3.0 s |
| Held afterwards | 8 B/px | 8 B/px |

One trap worth passing on: the depth percentiles the ramp is stretched over tolerate a strided
sample, but the gradient reference an unreferenced DEM is normalised by does not - striding
smooths the field and reports a gentler slope than the DEM has, which came out as a visibly
different image. That one is taken from full-resolution bands spread down the raster instead.

Checked against the previous renderer on georeferenced and unreferenced DEMs, with and without
nodata, taller and shorter than one band: no pixel differs by more than 4 of 255.

### Nodata was painted instead of left clear — ADOPT (`3d64843`)

A DEM was built as an `RGB32` image, which has no alpha to respect. Nodata was already being
written with an alpha of zero, and `RGB32` painted it black rather than letting the background
through the way an RGB map's nodata margin does. It is an `ARGB32` image now.

The same commit fixes a worse version of this after co-registration. The transform filled
everything outside the map with the channel's nodata value, but a channel only learns that value
when it is first displayed and holds `None` until then, so an alignment run before ever opening
the DEM filled with zero instead. Zero is a plausible elevation, and a shallow one against a
reef at eight metres, so the depth ramp coloured the whole margin at its shallow end. The fill
and the nodata the copy declares now come from the file being transformed.

> **A DEM aligned before this fix carries zeros rather than nodata** and will still show them.
> Those copies have to be made again; the fix cannot repair what is already written.

---

## Workflow and correctness

### Labelling a list of points from the keyboard — ADOPT (`5f2f776`)

**Upstream:** stepping between rows needs the data table focused, but `QAbstractItemView` consumes
every letter for its type-ahead search, so `A` never reaches `TagLab.keyPressEvent`.

Clicking the viewer to make `A` work then handed the arrow keys back to the viewer, which panned the
map instead of advancing to the next point — so labelling a list of points from the keyboard was not
possible at all. The table now ignores unmodified letters and digits so they propagate to the main
window, and the row selection survives assignment, so `A`, `↓`, `A`, `↓` works straight through.

Navigation is untouched: arrows, Home/End, Page Up/Down, Tab and Space still reach the table, as
does anything with Ctrl or Alt held. Checked key by key against a stock `QTableView`. The only loss
is the table's type-ahead search, which the panel's Search Id box already covers.

### Ask to save only when something has changed — ADOPT (`c74d13f`)

**Upstream:** closing asks whether to save whenever the project has a filename — so it asks every
time, including immediately after a save.

Rather than marking the project dirty from the many places that mutate it, where one missed call
loses work, the project is compared against the one last written or read using a hash of the same
serialisation `save()` performs. That answers the question directly — would the file on disk differ
— so no edit can be missed. `Project.serialize()` is split out of `save()` for this, and
`fingerprint()` hashes as it goes rather than building the whole string.

Two data-loss bugs fall out of the same change. A project that had *never* been saved was not asked
about at all, so a whole session could be closed away without a word; it is now asked about, and Yes
routes to Save As. And answering Yes then cancelling Save As no longer closes and loses the work.

The check costs roughly 1 second per 1.5 million contour points — about 2.5 s for 4000 regions —
once, at close, under a wait cursor.

### Ask before opening a project over unsaved work — ADOPT (`ae4379d`)

**Upstream:** File → Open and the recent-files list replace the current project without a word.

A session of unsaved annotation could be lost by picking the wrong file. The guard sits in `load()`
rather than `openProject`, so both entry points are covered by one check, and it runs before
`resetAll()` so cancelling leaves the project untouched. Importing annotations is deliberately left
alone — it merges rather than replaces, so there is nothing to lose.

### Console warnings, one of which was a real defect — ADOPT (`79f6ce2`, `b9d3a76`)

`undrawAnnPoint` called `scene.removeItem` on all four of a point's graphics items with no check, so
a point that had not been drawn — or was being undrawn twice — printed
`QGraphicsScene::removeItem: cannot remove 0-item` four times. `drawPointAnn` had the matching
problem: it removed `id_item` under a guard that only tested `cross1_gitem`, then rebuilt it without
clearing.

The rest were library noise: `weights_only=False` on all ten `torch.load` calls, `indexing='ij'` on
the distance-map meshgrid, the Albumentations update check disabled, and two files left open at
startup. The overflow in the 4-clicks sigmoid is suppressed rather than rewritten — `scipy.expit`
was measured against the current expression and flips about one thresholded pixel in eighty million,
which is not worth moving anyone's published numbers to silence a warning.

### The DEM view, coloured by depth — DISCUSS (`a09704b`)

**Upstream:** a global min/max greyscale ramp.

That is unusable when the raster spans metres of depth and the structure of interest is centimetres
— local contrast measured 1.83 grey levels against 40.25 for hillshade. The DEM is now drawn as
Metashape draws it: depth through a blue-to-red ramp with hillshade multiplied over the top, since
colour alone cannot show structure at this scale and shading alone cannot show depth. The ramp is
stretched over the middle 96% of depths so one spike cannot flatten it, and shading has an ambient
floor so colour still reads on faces turned away from the light. Pixels with a valid depth but a
nodata neighbour are lit flatly rather than left dark, which stops the survey boundary being
outlined in black.

This is a display default, hence flagged.

---

## Fork-only — do not merge

### The forced-update lockout is disabled — FORK ONLY (`fed07dc`)

`checkNewVersion()` is gated behind `CHECK_FOR_UPDATES`, off by default, so an upstream release
cannot block this build and startup does not wait on a network request.

### `update.py` points at this fork and never deletes — FORK ONLY (`a1a567e`, `dca9556`)

It now updates from our repository, which is what users of this build should receive.

One detail may be worth your attention regardless: **the upstream removal loop joins `filename`, the
name of the downloaded zip, instead of `file_name`, the directory it is iterating** — so it never
actually deleted anything. Had it worked as written, it would have removed `coraline/`, `docs/`,
`fonts/`, `icons/`, `source/` and `.github/`, taking with them any custom label image, dictionary or
project folder kept inside the TagLab directory. Our version verifies the download into a temporary
folder before writing anything, overwrites only shipped files, and lists rather than removes
leftovers. It also drops the `distutils` import, which is gone in Python 3.12.

---

## What we have not done

- **No automated test suite.** Verification was scripted end-to-end runs driving the real
  application — startup, load, DEM, export, sampling, tools, save state — plus measurements against
  synthetic geometry of known area. These are not committed as tests; they were built per change.
- **One platform.** Everything was exercised on Windows 11 with a CUDA GPU. The macOS and CPU-only
  paths were reasoned about and their timings measured on CPU here, but not run on Mac hardware.
- **The interface changes were measured, not looked at.** Column widths were read back from the
  header, and the icons were checked by rendering the cells and finding where the ink landed. That
  catches a mis-sized or off-centre element but not one that is merely ugly, and the display it was
  measured on renders text at 34 px, so the proportions are worth a glance on an ordinary one.
- **The Qt paint limit still exists** for the dataset export's tile preview, which is skipped with a
  message past 32767 px. Everything else on that path is free of it.
- **Rotated working areas are exact for counts, approximate for raster crops**, as described above.
- **The upstream georeferencing work is our fork point, not a merge.** We branched at `0150d84` and
  have taken nothing since; there is nothing of ours in your history to untangle.

---

## Getting the code

Each commit is self-contained with its reasoning and measurements in the message, so individual
changes can be cherry-picked without taking the rest.

```bash
git remote add perry https://github.com/wogreene/TagLab.git
git fetch perry
git log --oneline 0150d84..perry/main
git cherry-pick 73bb9f5   # for example, the surface area fix
```

Happy to split any of these into separate pull requests, rebase onto current `main`, or answer
questions about the measurements.
