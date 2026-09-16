# -*- coding: utf-8 -*-
"""
/***************************************************************************
 DEMto3D
                                 A QGIS plugin
 Description
                             -------------------
        copyright            : (C) 2026 by Javier
        email                : demto3d@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
import collections
import copy
import math
import struct
import traceback
from osgeo import gdal

from qgis.core import QgsTask, QgsPointXY, QgsCoordinateTransform, QgsProject


class ModelTask(QgsTask):
    pto = collections.namedtuple('pto', 'x y z')

    def __init__(self, parameters):
        # QgsTask verlangt den Namen und die Flags
        super().__init__("DEMto3D Model Building", QgsTask.CanCancel)
        self.parameters = parameters
        self.matrix_dem = []
        self.baseModel = self.parameters["baseModel"]

    def run(self):
        print("[DEMto3D] ModelTask.run() wurde von QGIS gestartet.")
        try:
            # 1. Layer-Objekt ermitteln
            layer_param = self.parameters["layer"]
            layer = None

            if isinstance(layer_param, str):
                layers = QgsProject.instance().mapLayersByName(layer_param)
                if layers:
                    layer = layers[0]
                else:
                    all_layers = QgsProject.instance().mapLayers().values()
                    layer = next((l for l in all_layers if l.source() == layer_param), None)
            else:
                layer = layer_param

            if not layer:
                print(f"[DEMto3D] Fehler: Rasterlayer '{layer_param}' nicht gefunden.")
                return False

            # --- CRS-Anpassung ---
            # Quell-CRS (Raster) und Ziel-CRS (Projekt) abfragen
            src_crs_wkt = layer.crs().toWkt()
            project_crs = QgsProject.instance().crs()
            dst_crs_wkt = project_crs.toWkt()

            source_path = layer.source()

            # 2. Parameter auslesen
            width_mm = self.parameters["width"]
            height_mm = self.parameters["height"]
            spacing_mm = self.parameters["spacing_mm"]
            scale = self.parameters["scale"]
            z_scale = self.parameters["z_scale"]
            h_base = self.parameters["z_base"]
            base_model = self.parameters["baseModel"]

            p = self.parameters
            roi_bounds = [
                p["roi_x_min"],
                p["roi_y_min"],
                p["roi_x_max"],
                p["roi_y_max"]
            ]

            # Schrittweite in Karteneinheiten berechnen (Projekt-Einheiten)
            spacing_map_units = (spacing_mm * scale) / 1000.0

            # 3. Multi-threaded GDAL Warp mit automatischer Reprojektion ins Projekt-CRS
            warp_options = gdal.WarpOptions(
                format='MEM',
                outputBounds=roi_bounds,
                xRes=spacing_map_units,
                yRes=spacing_map_units,
                srcSRS=src_crs_wkt,         # Explizit Quell-CRS definieren
                dstSRS=dst_crs_wkt,         # Auf Projekt-CRS reprojizieren
                resampleAlg=gdal.GRA_CubicSpline,
                multithread=True,
                warpOptions=['NUM_THREADS=ALL_CPUS']
            )

            ds = gdal.Warp('', source_path, options=warp_options)
            if not ds:
                print("[DEMto3D] GDAL Warp konnte kein Dataset erstellen.")
                return False

            band = ds.GetRasterBand(1)
            raw_matrix = band.ReadAsArray()
            nodata_val = band.GetNoDataValue()
            ds = None  # Speicher freigeben

            if self.isCanceled() or raw_matrix is None:
                return False

            # 4. Matrix verarbeiten
            rows, cols = raw_matrix.shape
            self.matrix_dem = []

            for i in range(rows):
                if self.isCanceled():
                    return False

                row_list = []
                y_model = round(height_mm - (i * spacing_mm), 2)

                for j in range(cols):
                    val = float(raw_matrix[i, j])

                    # Ungültige Werte / NoData / Werte unter der Basis abfangen
                    if (nodata_val is not None and val == nodata_val) or math.isnan(val) or val <= h_base:
                        z_val = base_model
                    else:
                        z_val = round((val - h_base) / scale * 1000.0 * z_scale, 2) + base_model

                    x_model = round(j * spacing_mm, 2)
                    row_list.append(self.pto(x=x_model, y=y_model, z=z_val))

                self.matrix_dem.append(row_list)
                self.setProgress((i / rows) * 100)

            # Optionale Umkehrung verarbeiten, falls gefordert
            if self.parameters.get("z_inv") and self.matrix_dem:
                self.matrix_dem = self.matrix_dem_inverse_build(self.matrix_dem)

            print(f"[DEMto3D] ModelTask erfolgreich beendet. Matrix-Größe: {rows}x{cols}")
            return True

        except Exception as e:
            print(f"[DEMto3D] AUSNAHME in ModelTask.run(): {e}")
            traceback.print_exc()
            return False

    def matrix_dem_builder(self, dem_dataset):
        height = self.parameters["height"]
        width = self.parameters["width"]
        scale = self.parameters["scale"]
        spacing_mm = self.parameters.get("spacing_mm", 0.75)
        roi_x_min = self.parameters["roi_x_min"]
        roi_y_min = self.parameters["roi_y_min"]
        h_base = self.parameters["z_base"]
        z_scale = self.parameters["z_scale"]
        projected = self.parameters["projected"]

        dem_col = dem_dataset.RasterXSize
        dem_row = dem_dataset.RasterYSize
        geotransform = dem_dataset.GetGeoTransform()
        dem_x_min = geotransform[0]
        dem_y_max = geotransform[3]
        dem_y_min = dem_y_max + dem_row * geotransform[5]
        dem_x_max = dem_x_min + dem_col * geotransform[1]

        rectParam = self.parameters["roi_rect_Param"]
        rotation = rectParam["rotation"]

        spacing_deg = 0
        if not projected:
            spacing_deg = spacing_mm * rectParam["width"] / width

        row_stl = int(math.ceil(height / spacing_mm) + 1)
        col_stl = int(math.ceil(width / spacing_mm) + 1)
        matrix_dem = [[None for _ in range(col_stl)] for _ in range(row_stl)]

        source = self.parameters["crs_map"]
        target = self.parameters["crs_layer"]
        transform = None
        if source != target:
            transform = QgsCoordinateTransform(source, target, QgsProject.instance())

        var_y = height
        total_steps = row_stl

        for i in range(row_stl):
            if self.isCanceled():
                return []

            self.setProgress((i / total_steps) * 100)

            var_x = 0
            for j in range(col_stl):
                if self.isCanceled():
                    return []

                x_model = round(var_x, 2)
                y_model = round(var_y, 2)

                if projected:
                    x0, y0 = getPolarPoint(roi_x_min, roi_y_min, rotation, x_model * scale / 1000)
                    x, y = getPolarPoint(x0, y0, rotation + math.pi * 0.5, y_model * scale / 1000)
                else:
                    x0, y0 = getPolarPoint(roi_x_min, roi_y_min, rotation, x_model * spacing_deg / spacing_mm)
                    x, y = getPolarPoint(x0, y0, rotation + math.pi * 0.5, y_model * spacing_deg / spacing_mm)

                if transform:
                    pt = transform.transform(QgsPointXY(x, y))
                    x, y = pt.x(), pt.y()

                col_dem = int(math.floor((x - dem_x_min) * dem_col / (dem_x_max - dem_x_min)))
                if col_dem >= dem_col:
                    col_dem = dem_col - 1

                row_dem = int(math.floor((dem_y_max - y) * dem_row / (dem_y_max - dem_y_min)))
                if row_dem >= dem_row:
                    row_dem = dem_row - 1

                if col_dem < 0 or row_dem < 0:
                    z_model = self.baseModel
                else:
                    z_val = self.get_dem_z(dem_dataset, col_dem, row_dem)
                    if z_val <= h_base or math.isnan(z_val):
                        z_model = self.baseModel
                    else:
                        z_model = round((z_val - h_base) / scale * 1000 * z_scale, 2) + self.baseModel

                matrix_dem[i][j] = self.pto(x=x_model, y=y_model, z=z_model)

                var_x += spacing_mm
                if var_x > width:
                    var_x = width

            var_y = spacing_mm * (row_stl - (i + 2))

        return matrix_dem

    @staticmethod
    def get_dem_z(dem_dataset, x_off, y_off):
        try:
            band = dem_dataset.GetRasterBand(1)
            data_types = {'Byte': 'B', 'UInt16': 'H', 'Int16': 'h',
                          'UInt32': 'I', 'Int32': 'i', 'Float32': 'f', 'Float64': 'd'}
            data = band.ReadRaster(x_off, y_off, 1, 1, 1, 1, band.DataType)
            if data is None:
                return 0.0
            type_code = data_types.get(gdal.GetDataTypeName(band.DataType), 'f')
            return struct.unpack(type_code, data)[0]
        except Exception:
            return 0.0

    @staticmethod
    def matrix_dem_inverse_build(matrix_dem_build):
        if not matrix_dem_build or len(matrix_dem_build) == 0:
            return []
        rows = len(matrix_dem_build)
        cols = len(matrix_dem_build[0])

        matrix_dem = copy.deepcopy(matrix_dem_build)
        z_max = matrix_dem_build[0][0].z
        for i in range(rows):
            for j in range(cols):
                if matrix_dem_build[i][j].z > z_max:
                    z_max = matrix_dem_build[i][j].z

        for i in range(rows):
            for j in range(cols):
                currcol = (cols - 1) - j
                new_z = z_max - matrix_dem_build[i][currcol].z + 2
                matrix_dem[i][j] = matrix_dem[i][j]._replace(z=new_z)

        return matrix_dem


def getPolarPoint(x0, y0, angle, dist):
    x = x0 + dist * math.cos(angle)
    y = y0 + dist * math.sin(angle)
    return [x, y]