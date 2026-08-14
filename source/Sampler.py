
import math
import numpy as np
import random
from source.Mask import checkIntersection


class Sampler(object):
    """
    """
    def __init__(self, method, number, offset, width, height):

        # sampling area parameters
        self.method = method
        self.number = number
        self.offset = int(offset)
        self.width = int(width)
        self.height = int(height)
        self.sampling_areas = []
        self.points = []

    def generate(self, top, left):
        """
        Generate samples inside a sampling area.
        """

        w = self.width
        h = self.height
        xstart = left + self.offset
        xend = left + w - self.offset
        ystart = top + self.offset
        yend = top + h - self.offset


        if self.method == 'Grid':

            area_cell = ((w - (2 * self.offset)) * (h-(2 * self.offset))) / self.number
            side_cell = int(math.sqrt(area_cell))

            ncol= round((w - (2 * self.offset))/side_cell)
            nrow = round((h - (2 * self.offset))/side_cell)

            for c in range(0, ncol):
                for r in range(0, nrow):
                    xc = xstart + c * side_cell
                    yc = ystart + r * side_cell
                    point = (xc + (side_cell/2), yc + (side_cell/2))
                    self.points.append(point)

        elif self.method == 'Random':

            counter = 0
            while counter < self.number:
                x = random.randint(int(xstart), int(xend))
                y = random.randint(int(ystart), int(yend))
                counter += 1
                self.points.append((x, y))

        elif self.method == 'Stratified':

            area_cell = ((w - (2 * self.offset)) * (h-(2 * self.offset))) / self.number
            side_cell = int(math.sqrt(area_cell))

            ncol= round((w - (2 * self.offset))/side_cell)
            nrow = round((h - (2 * self.offset))/side_cell)

            for c in range(0, ncol):
                for r in range(0, nrow):
                    x = random.randint(xstart + c * side_cell, xstart + c * side_cell + side_cell)
                    y = random.randint(ystart + r * side_cell, ystart + r * side_cell + side_cell)
                    self.points.append((x, y))

    def generateWholeMap(self, map_width, map_height, valid_mask=None):
        """
        Generate samples over the whole map rather than inside a sampling area.

        valid_mask is a boolean array covering the map, normally read at reduced resolution,
        marking the pixels that carry data; points are only placed where it is True. Pass None
        to sample the full rectangle. The mask does not have to match the map's resolution:
        positions are scaled into it.

        The requested number of points is spread over the area that actually carries data, not
        over its bounding box, so cropping a map to a non-rectangular ROI does not quietly
        reduce the number of samples that land inside it.
        """

        self.reset()

        xstart = self.offset
        ystart = self.offset
        xend = map_width - self.offset
        yend = map_height - self.offset

        if xend <= xstart or yend <= ystart:
            return

        w = xend - xstart
        h = yend - ystart

        def is_valid(x, y):
            if valid_mask is None:
                return True
            mh, mw = valid_mask.shape
            mx = min(mw - 1, max(0, int(x * mw / map_width)))
            my = min(mh - 1, max(0, int(y * mh / map_height)))
            return bool(valid_mask[my, mx])

        coverage = 1.0
        if valid_mask is not None:
            mh, mw = valid_mask.shape
            r0 = min(mh - 1, max(0, int(ystart * mh / map_height)))
            r1 = min(mh, max(r0 + 1, int(yend * mh / map_height)))
            c0 = min(mw - 1, max(0, int(xstart * mw / map_width)))
            c1 = min(mw, max(c0 + 1, int(xend * mw / map_width)))
            coverage = float(valid_mask[r0:r1, c0:c1].mean())
            if coverage <= 0.0:
                return

        if self.method == 'Random':
            # rejection sampling, bounded so that a mostly empty map cannot spin forever
            attempts = 0
            max_attempts = int(self.number / max(coverage, 0.01)) * 20 + 10000
            while len(self.points) < self.number and attempts < max_attempts:
                attempts += 1
                x = random.randint(int(xstart), int(xend))
                y = random.randint(int(ystart), int(yend))
                if is_valid(x, y):
                    self.points.append((x, y))
            return

        # Grid and Stratified: size the cell against the area that carries data
        area_cell = (w * h * coverage) / float(max(self.number, 1))
        side_cell = max(1, int(math.sqrt(area_cell)))

        ncol = max(1, round(w / side_cell))
        nrow = max(1, round(h / side_cell))

        for c in range(0, ncol):
            for r in range(0, nrow):
                if self.method == 'Stratified':
                    x = random.randint(xstart + c * side_cell,
                                       xstart + c * side_cell + side_cell)
                    y = random.randint(ystart + r * side_cell,
                                       ystart + r * side_cell + side_cell)
                else:
                    x = xstart + c * side_cell + side_cell / 2
                    y = ystart + r * side_cell + side_cell / 2

                if x <= xend and y <= yend and is_valid(x, y):
                    self.points.append((x, y))

    def overlap(self, sampling_area):
        """
        Check if the given sampling area overlaps with the existing ones.
        """

        for sa in self.sampling_areas:
            if checkIntersection(sampling_area, sa):
                return True

        return False

    def generateInsideWA(self, working_area, number_of_areas, overlap=False):
        """
        Generate samples inside a working area.
        """

        self.reset()

        w = self.width
        h = self.height

        if overlap:
            for i in range(number_of_areas):
                offx = random.randint(0, working_area[2] - w - 1)
                offy = random.randint(0, working_area[3] - h - 1)
                self.sampling_areas.append([offy, offx, w, h])
        else:
            for i in range(1000):
                offx = random.randint(0, working_area[2] - w - 1)
                offy = random.randint(0, working_area[3] - h - 1)
                sampling_area = [offy, offx, w, h]
                if not self.overlap(sampling_area):
                    self.sampling_areas.append(sampling_area)

                if len(self.sampling_areas) >= number_of_areas:
                    break

        # generate samples
        for sampling_area in self.sampling_areas:
            top = sampling_area[0] + working_area[0]
            left = sampling_area[1] + working_area[1]
            self.generate(top, left)

            sampling_area[0] = top
            sampling_area[1] = left

    def generateAlongTransect(self, transect, number_of_areas, equi_spaced=True, overlap=False):
        """
        Generate samples along a transect (the sampling areas are equally spaced or in a randomly positioned
        along the transect according to the regular flag).
        The transect is specified in the following format: [x1, y1, x2, y2]
        """

        self.reset()

        x1 = transect[0]
        y1 = transect[1]
        x2 = transect[2]
        y2 = transect[3]

        dx = x2-x1
        dy = y2-y1

        if equi_spaced:
            step = 1.0 / (number_of_areas-1)
            for i in range(number_of_areas):
                pos = step * i
                posx = x1 + dx * pos - self.width/2
                posy = y1 + dy * pos - self.height/2
                sampling_area = [posy, posx, self.width, self.height]
                self.sampling_areas.append(sampling_area)
                self.generate(posy, posx)
        else:
            # generate sampling areas
            for i in range(1000):
                alpha = random.random()
                posx = x1 + dx * alpha - self.width/2
                posy = y1 + dy * alpha - self.height/2
                sampling_area = [posy, posx, self.width, self.height]
                if not self.overlap(sampling_area):
                    self.sampling_areas.append(sampling_area)

                if len(self.sampling_areas) >= number_of_areas:
                    break

            # generate samples
            for sampling_area in self.sampling_areas:
                self.generate(sampling_area[0], sampling_area[1])

    def reset(self):
        """
        Reset the samples generator.
        """
        self.sampling_areas = []
        self.points = []

