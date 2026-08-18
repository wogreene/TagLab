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

import os
import shutil
import tempfile

# GDAL sizes its block cache at 5% of physical RAM unless told otherwise, which on a large
# machine means gigabytes held on top of the image being decoded. Decoding a map is a single
# sequential pass over the file, so every block is read exactly once and a large cache buys
# nothing: capping it measured 3 GB lower peak memory AND a 40% faster load on a 1.45 Gpx
# orthomosaic. Peak is what decides whether a small machine can open a file at all.
# An explicit GDAL_CACHEMAX in the environment still wins.
os.environ.setdefault("GDAL_CACHEMAX", "256")

from PyQt5.QtGui import QImage
from PyQt5.QtGui import QImageReader
import rasterio as rio
from rasterio.windows import Window
from source import genutils
import numpy as np
import math

# Above this many bytes of decoded pixels, the image is decoded into a memory-mapped scratch
# file rather than into anonymous memory. Anonymous memory has to be covered by RAM or the
# pagefile; a memory-mapped file does not, so the pages become evictable and the machine only
# has to hold the part of the map being looked at. Measured on a 2.5 GB buffer, this takes the
# private commit charge from 2.52 GB to zero.
MEMMAP_THRESHOLD_BYTES = 512 * 1024 * 1024


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

        # open handle of the scratch file behind _pixel_buffer, when one is used
        self._buffer_file = None

    def allocatePixelBuffer(self, h, w):
        """
        Allocate the (h, w, 4) byte buffer the decoded image is written into.

        Large buffers are backed by a scratch file so that they do not have to fit in RAM. The
        file deletes itself when its last handle closes - through O_TEMPORARY on Windows and by
        unlinking it immediately on everything else - so a crash cannot leave gigabytes behind.

        Falls back to ordinary memory whenever a scratch file cannot be made or there is not
        enough free disk, since that is merely the previous behaviour.
        """

        nbytes = h * w * 4

        if nbytes < MEMMAP_THRESHOLD_BYTES:
            return np.empty((h, w, 4), dtype=np.uint8)

        try:
            scratch_dir = tempfile.gettempdir()
            # leave room to spare: running the disk to zero is worse than using RAM
            if shutil.disk_usage(scratch_dir).free < nbytes * 1.1:
                return np.empty((h, w, 4), dtype=np.uint8)

            path = os.path.join(scratch_dir, "taglab-pixels-%d-%d.tmp" % (os.getpid(), id(self)))

            flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_TEMPORARY", 0)
            flags |= getattr(os, "O_BINARY", 0)

            fd = os.open(path, flags)
            handle = os.fdopen(fd, "w+b")
            if not hasattr(os, "O_TEMPORARY"):
                # POSIX: the file stays alive only through the open handle
                os.unlink(path)

            buffer = np.memmap(handle, dtype=np.uint8, mode="w+", shape=(h, w, 4))

        except Exception as e:
            print("Could not create a scratch file for the image, using memory instead: " + str(e))
            return np.empty((h, w, 4), dtype=np.uint8)

        self.releaseBufferFile()
        self._buffer_file = handle
        return buffer

    def releaseBufferFile(self):
        """
        Close the scratch file, which is what removes it from disk.
        """

        if self._buffer_file is not None:
            try:
                self._buffer_file.close()
            except Exception:
                pass
            self._buffer_file = None

    def __del__(self):
        # the mapping keeps the pixels valid for as long as anything still refers to them; this
        # only drops our handle, which is what lets the scratch file go
        self.releaseBufferFile()

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
                self.nodata = dem.nodata
                px_x, px_y = self.groundPixelSize(dem)
                h, w = dem.height, dem.width
                # read straight into the array that is kept, rather than reading one and
                # then casting it into another
                self.float_map = np.empty((h, w), dtype=np.float32)
                dem.read(1, out=self.float_map)

            # shaded relief rather than a flat grey ramp: on a reef DEM the depth range is
            # metres while the structure of interest is centimetres, so a global stretch
            # leaves the detail invisible.
            #
            # Drawn a band of rows at a time into the same kind of buffer the RGB channel
            # uses, so a large DEM can be backed by a scratch file and the intermediates
            # only ever exist for one band.
            buffer = self.allocatePixelBuffer(h, w)
            genutils.renderHillshadeInto(buffer, self.float_map, self.nodata, px_x, px_y)

            # keep a reference: QImage points at this memory instead of copying it
            self._pixel_buffer = buffer
            # ARGB32, not RGB32: nodata is written with an alpha of zero so it drops out
            # of the view entirely and the background shows through, the way a nodata
            # margin does on an RGB map. RGB32 ignores the alpha and paints it black.
            self.qimage = QImage(buffer.data, w, h, w * 4, QImage.Format_ARGB32)

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
            buffer = self.allocatePixelBuffer(h, w)

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
