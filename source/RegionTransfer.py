# Copy the regions of one timepoint of a project onto another one.

import numpy as np
import rasterio as rio

# a point of the source map and the same place of the target map must agree to better than this (pixel size ratio)
SCALE_TOLERANCE = 1e-6


def pixel_shift(source, target):
    """
    Offset (dx, dy), in whole pixels, that moves a point of the source map onto the same place of the target map.
    None if the two maps do not share a coordinate system.

    When both maps are georeferenced in the same coordinate system with the same pixel size, the offset comes from
    their georeferencing (so maps with different extents are fine). Otherwise the maps must have the same size and
    resolution, and the regions stay where they are.
    """

    if source.georef_filename and target.georef_filename:
        try:
            with rio.open(source.georef_filename) as s, rio.open(target.georef_filename) as t:
                if s.crs is not None and s.crs == t.crs:
                    # source pixel -> ground -> target pixel
                    m = ~t.transform * s.transform
                    if (abs(m.a - 1.0) < SCALE_TOLERANCE and abs(m.e - 1.0) < SCALE_TOLERANCE and
                            abs(m.b) < SCALE_TOLERANCE and abs(m.d) < SCALE_TOLERANCE):
                        return int(round(m.c)), int(round(m.f))
                    # georeferenced the same way but at another scale or rotation: needs resampling, not a shift
                    return None
        except Exception:
            # unreadable georeferencing: judge the maps by their size
            pass

    same_size = source.width == target.width and source.height == target.height
    same_resolution = abs(source.pixelSize() - target.pixelSize()) < 1e-9
    if same_size and same_resolution:
        return 0, 0

    return None


def copy_regions(source, target, shift):
    """
    Copies of the regions of the source map, moved by the shift, ready to be added to the target map. The regions
    that fall completely outside of the target map are left out; their number is returned too.
    """

    blobs = source.annotations.computeBlobsAffineTransform(np.eye(2), np.array(shift, dtype=float))

    inside = []
    for blob in blobs:
        top, left, width, height = blob.bbox
        if left + width <= 0 or top + height <= 0 or left >= target.width or top >= target.height:
            continue
        inside.append(blob)

    return inside, len(blobs) - len(inside)


def find_table(project, image_a, image_b):
    """
    The correspondences table between the two maps, whichever way it was made (a table runs from a source map to a
    target map), or None.
    """

    for source, target in ((image_a, image_b), (image_b, image_a)):
        table = (project.correspondences or {}).get(source.id + "-" + target.id)
        if table is not None:
            return table

    return None


def link_orientation(project, copied_from, copied_to):
    """
    (source, target) of the table that links the two maps: that of an existing table, otherwise the older map is the
    source, as the match tool is normally used.
    """

    table = find_table(project, copied_from, copied_to)
    if table is not None:
        return table.source, table.target

    older = copied_from.acquisition_date and copied_to.acquisition_date
    if older and copied_from.acquisition_date > copied_to.acquisition_date:
        return copied_to, copied_from

    return copied_from, copied_to


def link_regions(project, copied_from, copied_to, copies):
    """
    Match the regions of the two maps the way Compute Automatic Matches does, which also sets up the genets, so that the
    copies made on copied_to are linked to their originals. The regions matched are not left flagged as still to be
    checked. Returns the number of matches.
    """

    source, target = link_orientation(project, copied_from, copied_to)
    project.computeCorrespondences(project.images.index(source), project.images.index(target))

    table = project.correspondences[source.id + "-" + target.id]
    column = 'Blob2' if table.target is copied_to else 'Blob1'

    matched = table.data[(table.data['Blob1'] != -1) & (table.data['Blob2'] != -1)]
    matched_ids = set(int(i) for i in matched[column])
    for blob in copies:
        if blob.id in matched_ids:
            blob.correspondence_to_check = False

    return len(matched)
