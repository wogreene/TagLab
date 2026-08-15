
import numpy as np
import json
import math
import os

from osgeo import gdal, osr
import osgeo.ogr as ogr
import rasterio as rio
from rasterio.plot import reshape_as_raster
from rasterio.mask import mask
from rasterio.control import GroundControlPoint
from rasterio.transform import from_origin, from_gcps
from affine import Affine
from scipy import ndimage
import pandas as pd
from source.Blob import Blob
from source.Shape import Shape
from source.Mask import subtract
from shapely.geometry import Polygon


def mm_to_degrees(mm_pixel_size, center_lat):
    """
    This function converts the length in latitude and longitude degrees.
    One degree of Latitude is always approximately 111.1 km.
    The distance of one degree of Longitude shrinks as you move away from the Equator.
    """

    # Constants
    KM_PER_DEGREE_LAT = 111.1
    KM_PER_DEGREE_LON_EQUATOR = 111.32

    # Convert mm to km
    km_pixel_size = mm_pixel_size / 1000000.0

    # Calculate degrees
    res_decimal_degree_lat = km_pixel_size / KM_PER_DEGREE_LAT

    # Adjust longitude for the curvature of the Earth
	# This is called Napkin formula, it is an approximation that gives an error of about 0.3%-0.5%
	# Acceptable for distances in the order of hundreds of meters.
    res_decimal_degree_lon = km_pixel_size / (KM_PER_DEGREE_LON_EQUATOR * math.cos(math.radians(center_lat)))

    return res_decimal_degree_lon, res_decimal_degree_lat

def georeferencingImageUsingTwoGCPs(img, pixel_size, x1, y1, lon1, lat1, x2, y2, lon2, lat2, output_file):
    """
    Assign the georeferencing information to the input image given a set of Ground Control Points.
    """

    # If input_image is (H, W, C), we need to reshape it to (C, H, W) for Rasterio
    width = img.shape[1]
    height = img.shape[0]
    count = img.ndim
    if count == 3 or count == 4:
        img = img.transpose(2, 0, 1)

    # Differences (deltas)
    dx = x2 - x1
    dy = y2 - y1
    dxp = lon2 - lon1
    dyp = lat2 - lat1

    lon_res, lat_res = mm_to_degrees(pixel_size, lat1)
    sx = lon_res
    sy = -lat_res  # the minus sign takes into account the fact that the direction of the latitude is opposite to the image Y coordinates

    # denominator for the rotation components
    denom = (sx * dx) ** 2 + (sy * dy) ** 2

    if denom < 1e-10:
        raise ValueError("Points are too close or scale factors are zero.")

    # Calculate rotation components
    cos_theta = (sx * dx * dxp + sy * dy * dyp) / denom
    sin_theta = (sx * dx * dyp - sy * dy * dxp) / denom

    # Construct Matrix A: R * S
    # A = [[sx*cos, -sy*sin], [sx*sin, sy*cos]]
    a11 = sx * cos_theta
    a12 = -sy * sin_theta
    a21 = sx * sin_theta
    a22 = sy * cos_theta

    A = np.array([
        [a11, a12],
        [a21, a22]
    ])

    # Solve for translation vector b: b = xp1 - A * x1
    x1_vec = np.array([x1, y1])
    xp1_vec = np.array([lon1, lat1])
    b = xp1_vec - A.dot(x1_vec)

    # Return the combined 2x3 matrix [A | b]
    affine_matrix = np.column_stack((A, b))

    transform = rio.Affine(affine_matrix[0][0], affine_matrix[0][1], affine_matrix[0][2],
						   affine_matrix[1][0], affine_matrix[1][1], affine_matrix[1][2])

    # save to a GeoTIFF
    with rio.open(
        output_file,
        'w',
        driver='GTiff',
        height=height,
        width=width,
        count=count,
        dtype=img.dtype,
        crs='EPSG:4326',
        transform=transform
    ) as dst:
        dst.write(img)


def georeferencingImageUsingGCPs(img, pix_coords, geo_coords, output_file):
    """
    Assign the georeferencing information to the input image given a set of Ground Control Points.
    """

    # If input_image is (H, W, C), we need to reshape it to (C, H, W) for Rasterio
    width = img.shape[1]
    height = img.shape[0]
    count = img.ndim
    if count == 3 or count == 4:
        img = img.transpose(2, 0, 1)

    # Define GCPs (x=Longitude, y=Latitude)
    gcps = []
    for i in range(int(len(pix_coords)/2)):
        gcp = GroundControlPoint(row=pix_coords[i*2+1], col=pix_coords[i*2], x=geo_coords[i*2], y=geo_coords[i*2+1])
        gcps.append(gcp)

    transform = from_gcps(gcps)

    # save to a GeoTIFF
    with rio.open(
        output_file,
        'w',
        driver='GTiff',
        height=height,
        width=width,
        count=count,
        dtype=img.dtype,
        crs='EPSG:4326',
        transform=transform,
    ) as dst:
        dst.write(img)


def copyGeoreferenceInformation(source, target, output_file):
	"""
	Copy the geoereference image from the source image to the target image, and save it.
	"""

	# Extract the georef information
	with rio.open(source) as ref:
		ref_transform = ref.transform
		ref_crs = ref.crs
		ref_meta = ref.meta.copy()

	# Update the metadata dictionary to match the reference
	# We keep the pixel count/dtype from the target, but take spatial info from ref

	width = target.shape[1]
	height = target.shape[0]
	count = target.ndim
	if count == 3 or count == 4:
		target = target.transpose(2, 0, 1)

	ref_meta.update({
		"driver": "GTiff",
		"height": height,
		"width": width,
		"count": count,
		"dtype": target.dtype,
		"transform": ref_transform,
		"crs": ref_crs
	})

	# Write the new file
	with rio.open(output_file, "w", **ref_meta) as dest:
			dest.write(target)

	print(f"Success! Georeferencing copied to {output_file}")

def georeferencingImage(img, pixel_size, anchor_x, anchor_y, anchor_lat, anchor_lon, output_file):
    """
    Given an image without georeferencing information assign georeferencing using WGS EPSG:4326 coordinates.
    """

    # If input_image is (H, W, C), we need to reshape it to (C, H, W) for Rasterio
    width = img.shape[1]
    height = img.shape[0]
    count = img.ndim
    if count == 3 or count == 4:
        img = img.transpose(2, 0, 1)

    # Calculate the latitude and the longitude of the top-left corner of the image
    lon_res, lat_res = mm_to_degrees(pixel_size, anchor_lat)
    lon_origin = anchor_lon - (anchor_x * lon_res)
    lat_origin = anchor_lat + (anchor_y * lat_res)

    # create the geotransform
    print(lon_origin)
    print(lat_origin)
    transform = from_origin(lon_origin, lat_origin, lon_res, lat_res)

    # write a GeoTiff
    with rio.open(
            output_file,
            'w',
            driver='GTiff',
            height=height,
            width=width,
            count=count,
            dtype=img.dtype,
            crs='EPSG:4326',
            transform=transform,
    ) as dst:
        dst.write(img)


def changeFormat(contour, transform):
    """
    convert blob coordinates for Polygon shapefiles. Coord are in pixels while pointsgeo are in mm
    """
    coords = []
    pointsgeo = []
    for coord in contour:
        coord = tuple(coord)
        coords.append(coord)

    if transform is not None:
        for points in coords:
            x = points[0]
            y = points[1]
            pointgeo = transform * (x, y)
            pointsgeo.append(pointgeo)
        return pointsgeo
    else:
        return coords


def changeFormatInv(coord, transform):
    """
    convert polygon coordinate in pixel coordinates
    # """
    # transformr = np.reshape(transform, (3, 3))
    # transformInv = inv(transformr)
    pointpixels = []
    #va controllato se esiste
    if transform is not None:
        for points in coord[0]:
            xref = points[0]
            yref = points[1]
            pointpix = ~transform * (xref, yref)
            pointpixels.append(pointpix)
        return pointpixels

def changeFormatInvPoint(coord, transform):
    """
    convert poligon coordinate in pixel coordinates
    # """
    if transform is not None:
        xref = coord[0]
        yref = coord[1]
        pointpix = ~transform * (xref, yref)
        return pointpix


def createPolygon(blob, transform):

    # load blob.contour and transform coordinate
    exterior = changeFormat(blob.contour, transform)
    exteriorPolygon = Polygon(exterior)

    inners=[]
    for inner in blob.inner_contours:
            interior=changeFormat(inner, transform)
            innerPolygon = Polygon(interior)
            inners.append(innerPolygon)
    newPolygon = Polygon(exteriorPolygon.exterior.coords, [inner.exterior.coords for inner in inners])

    return newPolygon


def createPolygonFromWorkingArea(working_area, transform):

    wa_coord = [(working_area[1], working_area[0]), (working_area[1] + working_area[2], working_area[0]), (working_area[1] + working_area[2] , working_area[0] + working_area[3]),(working_area[1], working_area[0]+ working_area[3])]

    # load blob.contour and transform coordinate
    wa_coord_change = changeFormat(wa_coord, transform)
    waPolygon = Polygon(wa_coord_change)

    return waPolygon


def read_attributes(filename):
    driver = ogr.GetDriverByName("ESRI Shapefile")
    dataSource = driver.Open(filename, 0)
    layer = dataSource.GetLayer(0)
    data = pd.DataFrame()
    for feat in layer:
        shpdict =json.loads(feat.ExportToJson())
        properties = shpdict['properties']
        if data.empty:
            data = pd.DataFrame.from_dict([properties])
        else:
            new_row = pd.DataFrame.from_dict([properties])
            data = pd.concat([data, new_row])
    return data


def read_regions_geometry(filename, georef_filename):

    img = rio.open(georef_filename)
    transform = img.transform

    driver = ogr.GetDriverByName("ESRI Shapefile")
    dataSource = driver.Open(filename, 0)
    layer = dataSource.GetLayer(0)


    #set spatial reference and transformation
    sourceprj = layer.GetSpatialRef()
    targetprj = osr.SpatialReference(wkt = img.crs.wkt)
    #need to check if sourceproj == targetproj
    reproject = osr.CoordinateTransformation(sourceprj, targetprj) #this is a transform

    blobList = []
    for feat in layer:
        transformed = feat.GetGeometryRef()
        transformed.Transform(reproject)

        shpdict = json.loads(feat.ExportToJson())
        if shpdict['geometry']['type'] == 'Polygon':
            blob = Blob(None, 0, 0, 0)
            coord = shpdict['geometry']['coordinates']
            outercontour = coord[0]
            outpointpixels = changeFormatInv([outercontour], transform)
            blob.createFromClosedCurve([np.asarray(outpointpixels)], False)
            for i in range(1, len(coord)):
                innercontourn_i = coord[i]
                innerpointpixels_i = changeFormatInv([innercontourn_i], transform)
                innerblob = Blob(None, 0, 0, 0)
                innerblob.createFromClosedCurve([np.asarray(innerpointpixels_i)], False)
                # FIXME: prevents problem if the innerblob size is less than one pixel, but it is not clear
                #  when it happens
                if innerblob.bbox[2] > 0.9 and innerblob.bbox[3] > 0.9:
                    (mask, box) = subtract(blob.getMask(), blob.bbox, innerblob.getMask(), innerblob.bbox)
                    if mask.any():
                        blob.updateUsingMask(box, mask.astype(int))
            blobList.append(blob)

    return blobList


def read_geometry(filename, georef_filename):

    img = rio.open(georef_filename)
    transform = img.transform

    driver = ogr.GetDriverByName("ESRI Shapefile")
    dataSource = driver.Open(filename, 0)
    layer = dataSource.GetLayer(0)

    shape_list = []
    for feat in layer:
        shpdict = json.loads(feat.ExportToJson())

        if shpdict['geometry']['type'] == 'Polygon':
            coord = shpdict['geometry']['coordinates']
            outercontour = coord[0]
            outpointpixels = changeFormatInv([outercontour], transform)

            inner_contours = []
            for i in range(1, len(coord)):
                innercontourn_i = coord[i]
                innerpointpixels_i = changeFormatInv([innercontourn_i], transform)
                inner_contours.append(np.asarray(innerpointpixels_i))

            shape = Shape(np.asarray(outpointpixels), inner_contours)
            shape_list.append(shape)

        if shpdict['geometry']['type'] == 'Point':
            coord = shpdict['geometry']['coordinates']
            coord_map = changeFormatInv([[coord]], transform)

            sh = Shape(np.asarray(coord_map), None)
            shape_list.append(sh)

    return shape_list



def write_shapefile(project, image, blobs, georef_filename, out_shp):
    """
    https://gis.stackexchange.com/a/52708/8104
    """
    scale_factor = image.pixelSize()
    date = image.acquisition_date
    # load georeference information to use
    img = rio.open(georef_filename)
    geoinfo = img.crs
    transform = img.transform
    annotations = image.annotations

    working_area = project.working_area

    if working_area is not None:
        # only the blobs inside the working area are considered
        blobs = annotations.calculate_inner_blobs(working_area)


    # create the list of visible instances
    name_list = []
    visible_blobs = []
    for blob in blobs:
        if blob.qpath_gitem.isVisible():
            index = blob.blob_name
            name_list.append(index)
            visible_blobs.append(blob)

    # SHAPEFILE NAMES CANNOT BE LONGER THAN 10 characters

    number_of_seg = len(name_list)
    dict = {
        'TL_id': np.zeros(number_of_seg, dtype = np.int64),
        'TL_Date': [],
        'TL_Class': [],
        'TL_Genet': np.zeros(number_of_seg, dtype = np.int64),
        'TL_Cx': np.zeros(number_of_seg),
        'TL_Cy': np.zeros(number_of_seg),
        'TL_Area': np.zeros(number_of_seg),
        'TL_SurfA': np.zeros(number_of_seg),
        'TL_Perim': np.zeros(number_of_seg),
        'TL_Note': []}

    for attribute in project.region_attributes.data:
        key = attribute["name"]
        if attribute['type'] in ['string', 'keyword']:
            dict[key] = []
        elif attribute['type'] in ['integer number', 'boolean']:
            dict[key] = np.zeros(number_of_seg, dtype = np.int64)
        elif attribute['type'] in ['decimal number']:
            dict[key] = np.zeros(number_of_seg, dtype = np.float64)
        else:
            # unknown attribute type, not saved
            pass

    for i, blob in enumerate(visible_blobs):
        dict['TL_id'][i] = blob.id
        dict['TL_Date'].append(date)
        dict['TL_Class'].append(blob.class_name)
        dict['TL_Cx'][i] = round(blob.centroid[0], 1)
        dict['TL_Cy'][i] = round(blob.centroid[1], 1)
        dict['TL_Area'][i] = round(blob.area * (scale_factor) * (scale_factor) / 100, 2)
        if blob.surface_area > 0.0:
            dict['TL_SurfA'][i] = round(blob.surface_area * (scale_factor) * (scale_factor) / 100, 2)
        dict['TL_Perim'][i] = round(blob.perimeter * scale_factor / 10, 1)

        if blob.genet is not None:
            dict['TL_Genet'][i] = blob.genet

        dict['TL_Note'].append(blob.note)

        for attribute in project.region_attributes.data:

            key = attribute["name"]

            try:
                value = blob.data[key]
            except:
                value = None

            if attribute['type'] == 'integer number':

                if value is not None:
                    dict[key][i] = value
                else:
                    dict[key][i] = 0

            elif attribute['type'] == 'boolean':

                if value is not None:
                    dict[key][i] = 1 if value else 0
                else:
                    dict[key][i] = 0

            elif attribute['type'] == 'decimal number':

                if value is not None:
                    dict[key][i] = value
                else:
                    dict[key][i] = np.NaN

            else:
                if value is not None:
                    dict[key].append(value)
                else:
                    dict[key].append('')

    # # convert blobs in polygons
    polygons = []
    for blob in visible_blobs:
        if blob.qpath_gitem.isVisible():
            polygon = createPolygon(blob, transform)
            polygons.append(polygon)

    # Now convert them to a shapefile with OGR
    outDriver = ogr.GetDriverByName('Esri Shapefile')
    outDataSource = outDriver.CreateDataSource(out_shp)
    srs = osr.SpatialReference()
    if geoinfo is not None:
        srs.ImportFromWkt(geoinfo.wkt)

    # create a layer
    outLayer = outDataSource.CreateLayer("polygon", srs, geom_type=ogr.wkbPolygon)
    OGRTypes = {int: ogr.OFTInteger, str: ogr.OFTString, float: ogr.OFTReal}
    defn = outLayer.GetLayerDefn()
    # Create attribute fields according to the data types


    for key in list(dict.keys()):

            if type(dict[key]) == list:
                outLayer.CreateField(ogr.FieldDefn(key, OGRTypes[str]))
            elif dict[key].dtype == np.int64 or dict[key].dtype == np.int32:
                outLayer.CreateField(ogr.FieldDefn(key, OGRTypes[int]))
            else:
                outLayer.CreateField(ogr.FieldDefn(key, OGRTypes[float]))

    for i in range(len(polygons)):
        feat = ogr.Feature(defn)
        geom = ogr.CreateGeometryFromWkb(polygons[i].wkb)
        feat.SetGeometry(geom)

        for key in list(dict.keys()):
            if type(dict[key]) == list:
                feat.SetField(key, dict[key][i])

            elif dict[key].dtype == np.int64 or dict[key].dtype == np.int32:
                feat.SetField(key, int(dict[key][i]))

            else:
                feat.SetField(key, float(dict[key][i]))

        # Make a geometry, from Shapely object
        outLayer.CreateFeature(feat)
        feat = geom = None  # destroy these

    # Save and close everything
    ds = layer = feat = geom = None

def load_georef(image):
    # load georeference information to use
    img = rio.open(image)
    geoinfo = img.crs
    transform = img.transform
    return geoinfo, transform

def saveClippedTiff(input, blobs, georef_filename, name):

    # load georeference information to use
    img = rio.open(georef_filename)
    geoinfo = img.crs
    transform = img.transform

    # convert blobs into polygons
    mypolygons = []
    for blob in blobs:
        if blob.qpath_gitem.isVisible():
            polygon = createPolygon(blob, transform)
            mypolygons.append(polygon)

    dataset = rio.open(input)
    out_image, out_transform = rio.mask.mask(dataset, mypolygons, crop=True)
    # num_non_null = (out_image != 500000).sum()
    out_meta = dataset.meta
    # area= out_meta['transform'][0] ** 2*out_image
    out_meta.update({"driver": "GTiff",
                      "height": out_image.shape[1],
                      "width": out_image.shape[2],
                      "transform": out_transform})

    with rio.open(name, "w", **out_meta) as dest:
        dest.write(out_image)

def saveGeorefLabelMap(label_map, georef_filename, working_area, out_name):

    ## TO DO: CLEAN UP THIS FUNCTION!

    # create a georeferenced label image (as raster)
    img = rio.open(georef_filename)
    meta = img.meta
    transform = img.transform
    crs = img.crs

    myLabel = reshape_as_raster(label_map)
    myLabel_meta = meta.copy()
    myLabel_meta.update({"dtype": rio.uint8,
                         "count": 3,
                         "nodata": None})
    with rio.open(out_name + ".tif", "w", **myLabel_meta) as dest:
        dest.write(myLabel)

    if working_area is not None:

        dataset = rio.open(out_name + ".tif")
        # convert the working area into a polygon
        working_area_polygon = createPolygonFromWorkingArea(working_area, transform)
        # crop the raster using the working area polygon
        out_image, out_transform = rio.mask.mask(dataset, [working_area_polygon], crop=True)
        out_meta = dataset.meta.copy()
        out_meta.update({"driver": "GTiff",
                          "height": out_image.shape[1],
                          "width": out_image.shape[2],
                          "transform": out_transform})
        dataset.close()

        with rio.open(out_name + ".tif", "w", **out_meta) as dest:
            dest.write(out_image)


# Vertical unit of a DEM, in millimetres. Photogrammetry packages (Metashape, Pix4D) write
# elevations in metres regardless of whether the horizontal CRS is projected, geographic or
# absent, so metres is the default.
DEM_Z_UNIT_TO_MM = 1000.0


def rasterSize(filename):
    """
    (width, height) of a raster, or None if it cannot be opened.
    """

    try:
        with rio.open(filename) as src:
            return src.width, src.height
    except Exception:
        return None


def estimateLoadedBytes(width, height):
    """
    Memory TagLab needs to hold a map of this size, at 4 bytes per pixel.
    """

    return width * height * 4


def availableMemoryBytes():
    """
    Physical memory currently free, or None where it cannot be determined.
    """

    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullAvailPhys)
            return None

        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")

    except Exception:
        return None


def suggestReductionFactor(width, height, budget_bytes):
    """
    Smallest power-of-two reduction that brings a map inside the given budget.

    Returns 1 when it already fits, or when there is nothing to go on.
    """

    if not budget_bytes or budget_bytes <= 0:
        return 1

    factor = 1
    while factor < 16 and estimateLoadedBytes(width // factor, height // factor) > budget_bytes:
        factor *= 2

    return factor


def createReducedResolutionCopy(src_filename, dst_filename, factor):
    """
    Write a copy of a map reduced by an integer factor, and return its path.

    The reduction is done as a new raster rather than by downscaling in memory, because the
    georeferencing then stays truthful: the copy carries a transform that matches its own
    pixels, so annotations, DEM alignment, surface area, shapefile and DXF export all keep
    working against it with no special cases. Downscaling only the pixels in memory would leave
    every pixel-to-world conversion in the program silently wrong by the reduction factor.

    Where the source has overview pyramids - which a photogrammetry ortho normally does - GDAL
    reads the reduction straight out of one instead of touching the full-resolution data.
    """

    if factor <= 1:
        return src_filename

    with rio.open(src_filename) as src:
        width = max(1, src.width // factor)
        height = max(1, src.height // factor)
        compress = (src.profile.get("compress") or "deflate")
        photometric = src.profile.get("photometric")

    options = ["TILED=YES", "BLOCKXSIZE=256", "BLOCKYSIZE=256",
               "COMPRESS=" + str(compress).upper(), "BIGTIFF=IF_SAFER"]
    if photometric and str(compress).lower() == "jpeg":
        options.append("PHOTOMETRIC=" + str(photometric).upper())

    gdal.UseExceptions()
    gdal.Translate(dst_filename, src_filename, width=width, height=height,
                   resampleAlg="average", creationOptions=options)

    return dst_filename


def readValidityMask(filename, max_size=8192, shrink=True):
    """
    Boolean mask of the pixels of a raster that actually carry data, read at reduced resolution.

    rasterio's dataset_mask covers all the ways a raster says "nothing here" - an alpha band, a
    nodata value, an internal mask - and returns everything valid when the file says nothing at
    all, which is the right answer for a plain JPEG. Reading it decimated keeps it small: a
    37268 x 38950 ortho comes back as a 14 MB array in a fraction of a second.

    With shrink set, the mask is eroded by one cell so that a point accepted against it is
    inside the surveyed area at full resolution too, rather than within a decimated cell of its
    edge.

    Returns (mask, width, height) where width and height are the raster's full pixel size.
    """

    with rio.open(filename) as src:
        factor = max(1, int(math.ceil(max(src.width, src.height) / float(max_size))))
        out_h = max(1, src.height // factor)
        out_w = max(1, src.width // factor)
        mask = src.dataset_mask(out_shape=(out_h, out_w)) > 0
        full_w, full_h = src.width, src.height

    if shrink and mask.all():
        # nothing is masked out, so there is no edge to stay clear of
        return mask, full_w, full_h

    if shrink:
        mask = ndimage.binary_erosion(mask, structure=np.ones((3, 3), bool), border_value=0)

    return mask, full_w, full_h


def demToOrthoMapping(ortho, dem, ortho_px_to_mm):
    """
    Work out how a DEM lines up with the ortho it belongs to, and how big a DEM pixel is.

    Returns (affine, dem_px_mm_x, dem_px_mm_y) where affine maps ortho pixel coordinates onto
    DEM pixel coordinates. Both arguments are open rasterio datasets.

    Three cases are supported, in order of preference:

      * both rasters georeferenced in the same CRS - the two geotransforms are composed, which
        handles any resolution ratio (integer or not), any origin offset and any rotation;
      * georeferenced in different CRSs - not handled here, the caller must reproject;
      * one or both unreferenced - the DEM is assumed to cover the same extent as the ortho,
        which is how a cropped DEM is normally produced, and the mapping reduces to a scale.

    The size of a DEM pixel is deliberately derived from the ortho's pixel size (which the user
    supplies in mm) multiplied by the ratio between the two rasters. That ratio is
    dimensionless, so this works whether the rasters are in metres, in degrees, or carry no
    georeferencing at all - no geodesy and no CRS-specific special cases.
    """

    georeferenced = (ortho.crs is not None and dem.crs is not None and
                     ortho.transform is not None and dem.transform is not None and
                     not ortho.transform.is_identity and not dem.transform.is_identity)

    if georeferenced:
        if ortho.crs != dem.crs:
            raise Exception(
                "The DEM is in " + str(dem.crs) + " but the map is in " + str(ortho.crs) +
                ". Please reproject the DEM to the same coordinate reference system.")

        # ortho pixel -> world -> DEM pixel
        affine = ~dem.transform * ortho.transform
        ratio_x = abs(dem.transform.a) / abs(ortho.transform.a)
        ratio_y = abs(dem.transform.e) / abs(ortho.transform.e)
    else:
        # no georeferencing to go on: assume the two rasters cover the same ground
        ratio_x = ortho.width / dem.width
        ratio_y = ortho.height / dem.height
        affine = Affine(1.0 / ratio_x, 0.0, 0.0, 0.0, 1.0 / ratio_y, 0.0)

    return affine, ortho_px_to_mm * ratio_x, ortho_px_to_mm * ratio_y


def demCellAreaRatio(z, px_mm_x, px_mm_y, nodata):
    """
    Surface area of each DEM cell divided by its planar area.

    Each cell is split into two triangles from its four corner heights and their true 3D areas
    are summed, which is the exact area of the interpolated surface. Unlike a slope-based
    formula this stays correct on near-vertical faces: a step of height H across a cell of
    width w contributes H*w, the area of that vertical strip. No cap is applied - a steep cell
    on a coral flank is real surface, and a 2.5D height field already under-counts overhangs.

    Cells touching nodata come back as NaN.
    """

    z = z.astype(np.float32, copy=True)
    if nodata is not None:
        z[z == nodata] = np.nan
    z[~np.isfinite(z)] = np.nan

    # elevations are often large numbers with small differences between neighbours (a reef DEM
    # may sit at -16 m with millimetre relief); shifting to a local origin before converting to
    # millimetres keeps the differences well away from float32's precision limit
    finite = np.isfinite(z)
    if finite.any():
        z -= np.float32(z[finite].min())
    z *= np.float32(DEM_Z_UNIT_TO_MM)

    z00 = z[:-1, :-1]
    z01 = z[:-1, 1:]
    z10 = z[1:, :-1]
    z11 = z[1:, 1:]

    planar = px_mm_x * px_mm_y

    # upper triangle (z00, z01, z10) and lower triangle (z11, z10, z01); for each, the cross
    # product of the two edge vectors has a constant z component equal to the planar area
    a = 0.5 * np.sqrt(((z01 - z00) * px_mm_y) ** 2 +
                      ((z10 - z00) * px_mm_x) ** 2 + planar ** 2)
    b = 0.5 * np.sqrt(((z10 - z11) * px_mm_y) ** 2 +
                      ((z01 - z11) * px_mm_x) ** 2 + planar ** 2)

    return (a + b) / planar


# A region's outline sometimes clips a few pixels of the substrate beside the colony - the lip
# of an overhang, or a crevice running past its edge. Those cells are a step between two
# surfaces rather than colony surface, and because a step of height H across a cell of width w
# contributes H*w, a handful of them can double a colony's area.
#
# They are separable from real steepness by how they are distributed: a crevice puts enormous
# values on the thin line where the step occurs, while a genuinely steep colony is steep
# broadly. Clipping each region against its own distribution therefore removes the intrusion
# and leaves real relief alone.
#
# 95 was chosen by measurement. Against a hemispherical cap of known area with a substrate
# crevice cut into it, the error goes from +67%/+92%/+28% (unclipped, for a 150mm/3-cell,
# 150mm/8-cell and 60mm/4-cell crevice) to -0.7%/-0.5%/-0.6%. The cost is negligible on
# colony-like surfaces - a clean dome loses 0.7%, and real reef patches with an uncapped ratio
# below 1.3 lose 0.9% - and only becomes large on rugged matrix, which is where an outline is
# most likely to be catching something that is not the colony anyway.
#
# Set to 100.0 to disable clipping entirely.
SURFACE_OUTLIER_PERCENTILE = 95.0


def calculateSurfaceAreas(ortho_filename, dem_filename, ortho_px_to_mm, blobs,
                          outlier_percentile=SURFACE_OUTLIER_PERCENTILE):
    """
    Set blob.surface_area, expressed in ortho pixels so that the existing conversion to cm2
    (area * pixel_size^2) applies unchanged.

    The blob outline stays at ortho resolution and only the per-cell area ratio is taken from
    the DEM, sampled bilinearly. Downsampling the outline onto a coarser DEM grid would
    quantise it to the DEM cell size, which on a small colony is a large and biased error;
    the area ratio, unlike a hard mask edge, interpolates cleanly.

    A blob is left blank (surface_area = 0) unless it is *entirely* covered by valid DEM.

    Returns a dict of blob id -> (DEM coverage fraction, fraction of area removed by the
    outlier clip), for reporting.
    """

    stats_by_blob = {}

    with rio.open(ortho_filename) as ortho, rio.open(dem_filename) as dem:

        affine, px_mm_x, px_mm_y = demToOrthoMapping(ortho, dem, ortho_px_to_mm)
        ratio = demCellAreaRatio(dem.read(1), px_mm_x, px_mm_y, dem.nodata)

    valid = np.isfinite(ratio)
    # bilinear sampling must not drag NaN into good areas, so interpolate a filled copy and
    # track validity separately
    ratio_filled = np.where(valid, ratio, 1.0)
    valid_f = valid.astype(np.float32)

    for blob in blobs:

        mask_blob = blob.getMask()
        rows, cols = np.nonzero(mask_blob)
        if rows.size == 0:
            blob.surface_area = 0.0
            stats_by_blob[blob.id] = (0.0, 0.0)
            continue

        # centres of the ortho pixels inside the blob, in ortho pixel coordinates
        ox = cols + int(blob.bbox[1]) + 0.5
        oy = rows + int(blob.bbox[0]) + 0.5

        # ...mapped onto the DEM, then shifted onto the cell-centre grid that ratio lives on
        dx = affine.a * ox + affine.b * oy + affine.c - 0.5
        dy = affine.d * ox + affine.e * oy + affine.f - 0.5

        inside = ((dx >= 0.0) & (dx <= ratio.shape[1] - 1) &
                  (dy >= 0.0) & (dy <= ratio.shape[0] - 1))

        coords = np.vstack([np.clip(dy, 0, ratio.shape[0] - 1),
                            np.clip(dx, 0, ratio.shape[1] - 1)])

        cover = ndimage.map_coordinates(valid_f, coords, order=1, mode="nearest")
        cover[~inside] = 0.0
        coverage = float((cover > 0.999999).sum()) / cover.size

        if coverage < 1.0:
            # partially outside the surveyed area: no meaningful surface area
            blob.surface_area = 0.0
            stats_by_blob[blob.id] = (coverage, 0.0)
            continue

        factors = ndimage.map_coordinates(ratio_filled, coords, order=1, mode="nearest")
        raw_total = float(factors.sum())

        if outlier_percentile < 100.0 and factors.size > 0:
            factors = np.minimum(factors, np.percentile(factors, outlier_percentile))

        blob.surface_area = float(factors.sum())
        trimmed = 1.0 - (blob.surface_area / raw_total) if raw_total > 0.0 else 0.0
        stats_by_blob[blob.id] = (coverage, trimmed)

    return stats_by_blob
