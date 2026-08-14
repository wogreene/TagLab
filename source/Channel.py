# TagLab
# A semi-automatic segmentation tool
#
# Copyright(C) 2020
# Visual Computing Lab
# ISTI - Italian National Research Council
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License (http://www.gnu.org/licenses/gpl.txt)
# for more details.

from PyQt5.QtGui import QImage
from PyQt5.QtGui import QImageReader
import rasterio as rio
from rasterio.windows import Window
from source import genutils
import numpy as np
import math
import os

class Channel(object):
    def __init__(self, filename = None, type = None):

        self.filename = filename      # path relative to the TagLab directory
        self.type = type              # RGB | DEM
        self.qimage = None            # cached QImage (to speed up visualization)
        self.float_map = None         # map of 32-bit floating point (e.g. to store high precision depth values)
        self.nodata = None            # invalid value

        # numpy buffer backing self.qimage for the RGB channel. QImage does NOT own this memory,
        # so the array has to stay alive for as long as the QImage does.
        self._pixel_buffer = None

    def loadData(self, taglab_dir):
        """
        Load the image data. The QImage is cached to speed up visualization.
        """

        filename = os.path.join(taglab_dir, self.filename)

        if self.type == "RGB":
            self.qimage = self.loadRGB(filename)

        # typically the depth map is stored in a 32-bit Tiff
        if self.type == "DEM":
            with rio.open(filename) as dem:
                self.float_map = dem.read(1).astype(np.float32)
                self.nodata = dem.nodata
                px_x, px_y = self.groundPixelSize(dem)

            # shaded relief rather than a flat grey ramp: on a reef DEM the depth range is
            # metres while the structure of interest is centimetres, so a global stretch
            # leaves the detail invisible
            self.qimage = genutils.floatmapToHillshadeQImage(self.float_map, self.nodata,
                                                             px_x, px_y)

        return self.qimage

    def groundPixelSize(self, dataset):
        """
        Size of one pixel on the ground, in the same unit as the DEM's elevations (metres).

        Returns (None, None) for an unreferenced raster, which tells the hillshade to work out
        its own scale from the data.
        """

        transform = dataset.transform
        if dataset.crs is None or transform is None or transform.is_identity:
            return None, None

        if not dataset.crs.is_geographic:
            return abs(transform.a), abs(transform.e)

        # geographic CRS: the transform is in degrees while the elevations are in metres, so
        # the two have to be reconciled before any slope means anything
        _, centre_lat = transform * (dataset.width / 2.0, dataset.height / 2.0)
        p = math.radians(centre_lat)
        m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * p) + 1.175 * math.cos(4 * p)
        m_per_deg_lon = 111412.84 * math.cos(p) - 93.5 * math.cos(3 * p)

        return abs(transform.a) * m_per_deg_lon, abs(transform.e) * m_per_deg_lat

    def loadRGB(self, filename):
        """
        Read the RGB channel through rasterio/GDAL and wrap it into a QImage.

        The pixels are decoded one horizontal stripe at a time, straight into the BGRA buffer
        that QImage expects, so the only full-size allocation is the buffer itself: 4 bytes per
        pixel, whatever the size of the map. The previous implementation read the whole
        (c, h, w) array, transposed it, built a second array and then QImage.copy()'d it,
        which peaked at about 12 bytes per pixel.
        """

        # rows decoded per iteration: keeps the temporary bounded (a few hundred MB at most)
        # instead of proportional to the height of the map
        STRIPE_ROWS = 1024

        with rio.open(filename) as src:
            w = src.width
            h = src.height
            count = src.count

            if count < 1:
                raise Exception("The image " + filename + " contains no band.")

            # a 4th band (or a 2nd one next to a grey band) is the alpha channel
            has_alpha = count == 4 or count == 2
            image_format = QImage.Format_ARGB32 if has_alpha else QImage.Format_RGB32

            # BGRA, which is the memory layout of both Format_RGB32 and Format_ARGB32
            buffer = np.empty((h, w, 4), dtype=np.uint8)

            color_bands = [1, 2, 3] if count >= 3 else [1]

            for y in range(0, h, STRIPE_ROWS):
                rows = min(STRIPE_ROWS, h - y)
                window = Window(0, y, w, rows)
                stripe = buffer[y:y + rows]

                pixels = src.read(color_bands, window=window)

                if count >= 3:
                    stripe[:, :, 2] = pixels[0]
                    stripe[:, :, 1] = pixels[1]
                    stripe[:, :, 0] = pixels[2]
                else:
                    # single band: replicate it over R, G and B
                    stripe[:, :, 0] = pixels[0]
                    stripe[:, :, 1] = pixels[0]
                    stripe[:, :, 2] = pixels[0]

                if has_alpha:
                    stripe[:, :, 3] = src.read(count, window=window)
                else:
                    stripe[:, :, 3] = 255

        # keep a reference: QImage points at this memory instead of copying it
        self._pixel_buffer = buffer

        return QImage(buffer.data, w, h, w * 4, image_format)

    def save(self):
        return { "filename": self.filename, "type": self.type }
