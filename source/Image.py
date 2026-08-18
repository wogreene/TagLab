import math

from source.Channel import Channel
from source.Blob import Blob
from source.Point import Point
from source.Shape import Layer, Shape
from source.Annotation import Annotation
from source.Grid import Grid
from skimage.transform import warp, AffineTransform
import rasterio as rio
import pandas as pd
import numpy as np
from scipy import ndimage as ndi
import os
import cv2


class Image(object):
    def __init__(self, rect=[0.0, 0.0, 0.0, 0.0],
                 map_px_to_mm_factor=1.0, width=None, height=None, channels=[], id=None, name=None,
                 acquisition_date="",
                 georef_filename="", workspace=[], metadata={}, annotations={}, layers=[],
                 grid={}, export_dataset_area=[], sampling_areas=[]):

        # we have to select a standanrd enforced!
        # in image standard (x, y, width height)
        # in numpy standard (y, x, height, width) #no the mixed format we use now I REFUSE to use it.
        # in range np format: (top, left, bottom, right)
        # in GIS standard (bottom, left, top, right)

        self.rect = rect  # coordinates of the image. (in the spatial reference system)
        self.map_px_to_mm_factor = map_px_to_mm_factor  # if we have a references system we should be able to recover this numner
        # otherwise we need to specify it.
        self.width = width
        self.height = height  # in pixels!

        self.annotations = Annotation()

        if annotations is not None:

            if type(annotations) == list:
                for data in annotations:
                    blob = Blob(None, 0, 0, 0)
                    blob.fromDict(data)
                    self.annotations.addBlob(blob)
            else:
                regions = annotations.get("regions")
                if regions is not None:
                    for data in regions:
                        blob = Blob(None, 0, 0, 0)
                        blob.fromDict(data)
                        self.annotations.addBlob(blob)

                points = annotations.get("points")
                if points is not None:
                    for data in points:
                        point = Point(0, 0, "Empty", 0)
                        point.fromDict(data)
                        self.annotations.addPoint(point)

        self.layers = list()
        for layer_data in layers:
            layer = Layer(layer_data["type"])
            layer.name = layer_data["name"]
            for data in layer_data["shapes"]:
                shape = Shape(None, None)
                shape.fromDict(data)
                layer.shapes.append(shape)
            self.layers.append(layer)

        self.channels = list(map(lambda c: Channel(**c), channels))

        self.id = id  # internal id used in correspondences it will never changes
        self.name = name  # a label for an annotated image
        self.workspace = workspace  # a polygon in spatial reference system (reserved for future uses)
        self.export_dataset_area = export_dataset_area  # this is the region exported for training
        self.acquisition_date = acquisition_date  # acquisition date is mandatory (format YYYY-MM-DD)
        self.georef_filename = georef_filename  # image file (GeoTiff) contained the georeferencing information
        self.metadata = metadata  # this follows image_metadata_template, do we want to allow freedom to add custome values?

        self.sampling_areas = list()
        if sampling_areas:
            self.sampling_areas = sampling_areas

        if grid:
            self.grid = Grid()
            self.grid.fromDict(grid)
        else:
            self.grid = None

        self.cache_data_table = None
        self.cache_labels_table = None

    def deleteLayer(self, layer):
        self.layers.remove(layer)

    def pixelSize(self):

        if self.map_px_to_mm_factor == "":
            return 1.0
        else:
            return float(self.map_px_to_mm_factor)

    def loadGeoInfo(self, filename):
        """
        Update the georeferencing information.
        """
        img = rio.open(filename)
        if img.crs is not None:
            # this image contains georeference information
            self.georef_filename = filename

    def addChannel(self, filename, type):
        """
        This image add a channel to this image. The functions update the size (in pixels) and
        the georeferencing information (if the image if georeferenced).
        The image data is loaded when the image channel is used for the first time.
        """

        img = rio.open(filename)

        # NOTE: the old 32767 x 32767 limit came from Qt's raster paint engine, whose coordinates
        # are clamped to 32767. That clamp only applies when *drawing into* an image; loading,
        # cropping and displaying a larger map works, so no dimension check is enforced here.
        # The practical limit is now memory: the map is held uncompressed at 4 bytes per pixel.

        if type == "DEM" and self.width is not None and self.height is not None:
            # A DEM does not have to share the ortho's grid. A DEM downsampled to, say, 2mm
            # against a 0.5mm ortho is a far lighter product, and where the two are
            # georeferenced their geotransforms say exactly how they line up; where they are
            # not, the DEM is taken to cover the same extent. Either way the ortho keeps
            # defining the pixel grid that annotations live in, so width/height are not touched.
            self.checkDEMIsCompatible(img)
        else:
            # all the channels sharing the ortho grid must have the same size
            if self.width is not None and self.height is not None:
                if self.width != img.width or self.height != img.height:
                    raise Exception("Size of the images is not consistent! It is " + str(img.width) + "x" +
                                    str(img.height) + ", should have been: " + str(self.width) + "x" + str(self.height))

            self.width = img.width
            self.height = img.height

        # georef_filename is what every georeferenced export uses to turn ortho pixels into world
        # coordinates, so it must name a raster on the ortho's own grid. A DEM only qualifies
        # when it happens to share that grid exactly.
        if img.crs is not None:
            if type != "DEM" or (img.width == self.width and img.height == self.height):
                self.georef_filename = filename

        self.channels.append(Channel(filename, type))

    def checkDEMIsCompatible(self, dem):
        """
        Verify that an open DEM raster can be matched to this image's ortho grid.

        Where both rasters are georeferenced the check is real: same CRS, and extents that
        actually overlap. Where either is unreferenced there is nothing to check against - the
        DEM is simply assumed to cover the same ground as the ortho, which is how a DEM cropped
        alongside its ortho is normally produced.
        """

        if dem.crs is None or not self.georef_filename:
            return

        try:
            ortho = rio.open(self.georef_filename)
        except Exception:
            return

        with ortho:
            if ortho.crs is None:
                return

            if ortho.crs != dem.crs:
                raise Exception("The DEM is in " + str(dem.crs) + " but the map is in " +
                                str(ortho.crs) + ". Please reproject the DEM to the same "
                                "coordinate reference system as the map.")

            ob, db = ortho.bounds, dem.bounds
            overlap_w = min(ob.right, db.right) - max(ob.left, db.left)
            overlap_h = min(ob.top, db.top) - max(ob.bottom, db.bottom)
            ortho_w = ob.right - ob.left
            ortho_h = ob.top - ob.bottom

            if overlap_w <= 0.0 or overlap_h <= 0.0:
                raise Exception("The DEM does not overlap the map at all. Please check that the "
                                "two files cover the same area.")

            covered = (overlap_w * overlap_h) / (ortho_w * ortho_h)
            if covered < 0.5:
                raise Exception("The DEM only covers " + str(round(covered * 100.0)) +
                                "% of the map. Please supply a DEM cropped to the same area.")

    def create_labels_table(self, labels):
        '''
        Creates a data table for the label panel
        '''

        if self.annotations.table_needs_update is False:
            return self.cache_labels_table
        else:
            dict = {
                'Visibility': np.zeros(len(labels), dtype=int),
                'Color': [],
                'Class': [],
                '#R': np.zeros(len(labels), dtype=int),
                '#P': np.zeros(len(labels), dtype=int),
                'Coverage': np.zeros(len(labels),dtype=np.float32)
            }

            for i, label in enumerate(labels):
                dict['Visibility'][i] = np.int32(label.visible)
                dict['Color'].append(str(label.fill))
                dict['Class'].append(label.name)
                count, new_area = self.annotations.calculate_perclass_blobs_value(label, self.map_px_to_mm_factor)
                countP = self.annotations.countPoints(label)
                dict['#R'][i] = count
                dict['#P'][i] = countP
                dict['Coverage'][i] = new_area


            # create dataframe
            df = pd.DataFrame(dict, columns=['Visibility', 'Color', 'Class', '#R', '#P','Coverage'])
            self.cache_labels_table = df
            self.annotations.table_needs_update = False
            return df

    def create_data_table(self):
        '''
        This create a data table only for the data panel view
        '''

        if self.annotations.table_needs_update is False:
            return self.cache_data_table
        else:
            scale_factor = self.pixelSize()

            # create a list of instances
            name_list = []
            visible_blobs = []
            # select ONLY visible blobs
            for blob in self.annotations.seg_blobs:
                if blob.qpath_gitem is not None:
                    if blob.qpath_gitem.isVisible():
                        index = blob.blob_name
                        name_list.append(index)
                        visible_blobs.append(blob)

            number_of_seg = len(visible_blobs)

            annpoint_list = []
            visible_annpoints = []
            for annpoint in self.annotations.annpoints:
                if annpoint.cross1_gitem is not None:
                    if annpoint.cross1_gitem.isVisible():
                        index = annpoint.id
                        annpoint_list.append(index)
                        visible_annpoints.append(annpoint)

            number_of_points = len(visible_annpoints)

            dict = {
                'Id': np.zeros(number_of_seg + number_of_points, dtype=int),
                'Group': [],
                'Type': [],
                'Class': [],
                'Area': np.zeros(number_of_seg + number_of_points),
                #'Surf. area': np.zeros(number_of_seg)
            }

            for i, blob in enumerate(visible_blobs):
                dict['Id'][i] = blob.id
                # blank rather than a number for a region that stands alone: ids start
                # at zero, so there is no spare value to stand for "no group"
                dict['Group'].append("" if blob.group is None else str(blob.group))
                dict['Type'].append('R')
                dict['Class'].append(blob.class_name)
                dict['Area'][i] = round(blob.area * (scale_factor) * (scale_factor) / 100, 2)
            #            if blob.surface_area > 0.0:
            #                dict['Surf. area'][i] = round(blob.surface_area * (scale_factor) * (scale_factor) / 100, 2)

            for i, annpoint in enumerate(visible_annpoints):
                dict['Id'][i + number_of_seg] = annpoint.id
                dict['Group'].append("")
                dict['Type'].append('P')
                dict['Class'].append(annpoint.class_name)
                dict['Area'][i + number_of_seg] = 0.0


            df = pd.DataFrame(dict, columns=['Id', 'Group', 'Type', 'Class', 'Area'])
            self.cache_data_table = df
            self.annotations.table_needs_update = False

            return df

    def updateChannel(self, filename, type):
        img = rio.open(filename)

        if type == "DEM" and self.width is not None and self.height is not None:
            # as in addChannel: a DEM may be at its own resolution
            self.checkDEMIsCompatible(img)
        else:
            # check image size consistency (all the channels must have the same size)
            if self.width is not None and self.height is not None:
                if self.width != img.width or self.height != img.height:
                    raise Exception("Size of the images is not consistent! It is " + str(img.width) + "x" +
                                    str(img.height) + ", should have been: " + str(self.width) + "x" + str(self.height))

        if img.crs is not None:
            if type != "DEM" or (img.width == self.width and img.height == self.height):
                self.georef_filename = filename

        for index, channel in enumerate(self.channels):
            if channel.type == type:
                self.channels[index] = Channel(filename, type)

    def hasDEM(self):
        """
        It returns True if the image has a DEM channel, False otherwise.
        """
        for channel in self.channels:
            if channel.type == "DEM":
                return True

        return False

    def getChannel(self, type):
        for channel in self.channels:
            if channel.type == type:
                return channel
        return None

    def getChannelIndex(self, channel):
        try:
            index = self.channels.index(channel)
            return index
        except:
            return -1

    def getRGBChannel(self):
        """
        It returns the RGB channel (if exists).
        """
        return self.getChannel("RGB")

    def getDEMChannel(self):
        """
        It returns the DEM channel (if exists).
        """
        return self.getChannel("DEM")

    def save(self):
        data = self.__dict__.copy()

        # cached tables MUST NOT be saved
        del data["cache_data_table"]
        del data["cache_labels_table"]

        return data

    def copyTransform(self, tag, rot, tra, borders, geoTransform=None, geoRef=None):
        """
        Create a new Image applying an affine transformation and adding borders
        :param: name the new name for the image (functioning also as id)
        :param: rot the rotation component in degrees
        :param: tra the translation component
        :param: borders of the new image (positive offset) [left, right, top, bottom]
        :param: geoTransform the transformation of the geo-reference
        :param: geoRef the geo-reference of the new image
        :returns: the newly created image
        """
        [leftB, rightB, topB, bottomB] = borders
        # Create a copy
        cpy = Image(
            rect=self.rect,
            map_px_to_mm_factor=self.map_px_to_mm_factor,
            width=0,
            height=0,
            # channels=self.channels,
            id=self.id + tag,
            name=self.id + tag,
            acquisition_date=self.acquisition_date,
            georef_filename=self.georef_filename,
            workspace=self.workspace,
            metadata=self.metadata,
            # annotations=self.annotations,
            layers=self.layers,
            grid=self.grid,
            export_dataset_area=self.export_dataset_area
        )
        # TODO: Remove
        R = cv2.getRotationMatrix2D((0, 0), -rot, 1.0)[::, :2]
        T = np.array([tra[0] + leftB, tra[1] + topB])
        # Add blobs
        new_blobs = self.annotations.computeBlobsAffineTransform(R, T)
        for blob in new_blobs:
            cpy.annotations.addBlob(blob)
        # Add channels
        for ch in self.channels:
            # A DEM does not have to share the ortho's grid. The alignment is expressed
            # in ortho pixels - the borders, the translation and the geotransform all
            # are - so a channel on a coarser grid has to be given the same movement
            # counted in its own pixels, and a geotransform carrying its own pixel size.
            # Handed the ortho's numbers as they stand it came out the wrong size in the
            # wrong place, and was then refused for covering a few percent of the map it
            # had just been aligned to.
            span = self.__channelSpan(ch)
            ch_borders = [int(round(b / span)) for b in borders]
            ch_tra = np.array([tra[0] / span, tra[1] / span])
            ch_geo = geoTransform
            if ch_geo is not None and span != 1.0:
                ch_geo = ch_geo * rio.transform.Affine.scale(span)

            newFilename, w, h = self.__updateChannel(ch, tag, -rot, ch_tra, ch_borders,
                                                     ch_geo, geoRef)
            # The ortho defines the pixel grid the annotations live in, so a DEM on a
            # coarser grid must not redefine it - it used to, whenever it was the last
            # channel round the loop.
            if ch.type != "DEM":
                cpy.width = w
                cpy.height = h
            # Add transformed channel
            cpy.addChannel(newFilename, ch.type)
        # Result
        return cpy

    def __creationOptions(self, src):
        """
        How the source raster is stored, so the aligned copy is written the same way.

        Without this an aligned copy came out uncompressed, which on a JPEG-compressed
        orthomosaic is an enormous file for no gain. The compression, its quality and
        the tiling are carried across; anything the driver will not accept for the data
        being written is dropped rather than failing the alignment.
        """

        options = {}

        structure = src.tags(ns="IMAGE_STRUCTURE")
        compression = structure.get("COMPRESSION", "")
        name = compression.upper()

        if "JPEG" in name:
            # reported as "YCbCr JPEG" when the colour space is YCbCr, which is not a
            # name the writer accepts - the two halves have to be given separately
            options["compress"] = "JPEG"
            if "YCBCR" in name or structure.get("SOURCE_COLOR_SPACE") == "YCbCr":
                options["photometric"] = "YCbCr"
            # the original quality is not recorded in the file, and the map is being
            # resampled and so re-encoded whatever happens; 90 keeps that cheap
            options["jpeg_quality"] = int(structure.get("JPEG_QUALITY", 90))
        elif compression:
            options["compress"] = compression
            predictor = structure.get("PREDICTOR")
            if predictor:
                options["predictor"] = int(predictor)

        profile = src.profile
        if profile.get("tiled"):
            options["tiled"] = True
            options["blockxsize"] = profile.get("blockxsize", 256)
            options["blockysize"] = profile.get("blockysize", 256)
        if profile.get("interleave"):
            options["interleave"] = profile["interleave"]

        return options

    def __channelSpan(self, channel):
        """
        How many of the ortho's pixels one of this channel's covers. One for a channel on
        the ortho's own grid, larger for a DEM at a coarser resolution.
        """

        if not self.width:
            return 1.0

        try:
            with rio.open(channel.filename) as probe:
                if probe.width:
                    return self.width / float(probe.width)
        except Exception:
            pass

        return 1.0

    def __updateChannel(self, channel, tag, rot, tra, borders, geoTransform=None, geoRef=None):
        """
        Create a new image applying a transformation to a channel
        :param: channel the channel to transform
        :param: tag the string to add to filename when creating the new one
        :param: rot the rotation degrees
        :param: tra the translation vector
        :param: borders the borders in order [left, right, top, bottom]
        :param: geoTransform the transformation of the geo-reference
        :param: geoRef the geo-reference of the new image
        :returns: newFilename, width, height of the new image
        """
        # Retrieve borders
        leftB, rightB, topB, bottomB = borders
        # Create new filename
        filename, _ = os.path.splitext(channel.filename)
        ext = ".png" if channel.type == "RGB" and geoRef is None else ".tiff"
        newFilename = filename + tag + ext

        padding = channel.nodata if channel.nodata is not None else 0

        # This used to pad the map, shift it back by the padding, then rotate and
        # translate it - three full-size copies, the last two of them float64 because
        # that is what skimage.warp returns whatever went in. Aligning a 28000 px map
        # asked for 22 GB in a single allocation and died there.
        #
        # The two transforms compose into one, and applying it a band at a time into an
        # output of the map's own dtype holds two bands rather than the whole map.
        # Checked against the code it replaces: identical to floating point noise.
        t1 = AffineTransform(scale=1.0, rotation=0, translation=(-leftB, -topB))
        t2 = AffineTransform(scale=1.0, rotation=math.radians(-rot),
                             translation=(tra[0] + leftB, tra[1] + topB))
        inverse_map = np.linalg.inv((t1 + t2).params)

        # ndimage reads the input at matrix @ output + offset, in (row, col) rather
        # than the (x, y) the transforms are built in, hence the swap.
        matrix = np.array([[inverse_map[1, 1], inverse_map[1, 0]],
                           [inverse_map[0, 1], inverse_map[0, 0]]])

        # A band is read on its own rather than out of a padded copy of the map, so it
        # carries a margin: bilinear sampling just outside the data has to blend with
        # the padding the way it did before, and with nothing there it would return the
        # fill value instead and eat a pixel off every edge.
        MARGIN = 2
        offset = np.array([inverse_map[1, 2] + MARGIN - topB,
                           inverse_map[0, 2] + MARGIN - leftB])

        with rio.open(channel.filename) as src:
            count, dtype = src.count, src.dtypes[0]
            h = src.height + topB + bottomB
            w = src.width + leftB + rightB

            profile = {
                "driver": "PNG" if ext == ".png" else "GTiff",
                "width": w, "height": h, "count": count, "dtype": dtype,
            }
            if ext != ".png":
                profile.update(self.__creationOptions(src))
            geoMat = rio.transform.Affine.translation(-leftB + rightB, -topB + bottomB)

            # given to the writer up front rather than set afterwards, which opened the
            # file as un-georeferenced and warned about it every time
            if ext != ".png" and geoRef is not None:
                profile["crs"] = geoRef
                profile["transform"] = geoTransform * geoMat
                profile["nodata"] = channel.nodata

            # JPEG cannot hold a float DEM, and some band counts it will not take
            # either, so a copied setting that does not suit what is being written is
            # dropped rather than stopping the alignment.
            try:
                writer = rio.open(newFilename, "w", **profile)
            except Exception:
                for key in ("compress", "jpeg_quality", "photometric", "interleave"):
                    profile.pop(key, None)
                writer = rio.open(newFilename, "w", **profile)

            with writer as dest:

                for band in range(1, count + 1):
                    data = np.pad(src.read(band), ((MARGIN, MARGIN), (MARGIN, MARGIN)),
                                  constant_values=padding)
                    out = np.empty((h, w), dtype=dtype)
                    ndi.affine_transform(data, matrix, offset=offset,
                                         output_shape=(h, w), output=out,
                                         order=1, mode="constant", cval=padding)
                    dest.write(out, band)
                    del data, out

        # Return (resource path, width, height)
        return newFilename, w, h
