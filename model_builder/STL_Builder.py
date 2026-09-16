# -*- coding: utf-8 -*-
"""
/***************************************************************************
 DEMto3D
                                 A QGIS plugin
 Description
                             -------------------
        copyright            : (C) 2022 by Javier
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

from builtins import str
from builtins import range
import collections
import struct
import math
import traceback
from qgis.core import QgsTask

BINARY_HEADER = "80sI"
BINARY_FACET = "12fH"


class STLTask(QgsTask):
    """Class where is built the stl file from the mesh point that decribe the model surface"""
    normal = collections.namedtuple('normal', 'normal_x normal_y normal_z')    normal = collections.namedtuple('normal', 'normal_x normal_y normal_z')
    pto = collections.namedtuple('pto', 'x y z')

    def __init__(self, parameters, stl_file, dem_matrix):
        super().__init__("DEMto3D STL Export", QgsTask.CanCancel)
        self.parameters = parameters
        self.stl_file = stl_file
        self.matrix_dem = dem_matrix

    def run(self):
        print("[DEMto3D] STLTask.run() wurde von QGIS gestartet.")
        try:
            x_models = self.parameters.get("divideCols", 1)
            y_models = self.parameters.get("divideRow", 1)

            width_model = self.parameters["width"] / x_models
            high_model = self.parameters["height"] / y_models
            total_ops = y_models * x_models
            current_op = 0

            for i in range(y_models):
                for j in range(x_models):
                    if self.isCanceled():
                        return False

                    path = self.stl_file
                    if (y_models * x_models > 1):
                        path = self.stl_file.split(".")[0] + '_' + str(i) + str(j) + '.stl'

                    x_min_model = width_model * j
                    y_min_model = self.parameters["height"] - i * high_model - high_model
                    x_max_model = width_model * j + width_model
                    y_max_model = self.parameters["height"] - i * high_model

                    dem_model = self.cut_dem(
                        self.matrix_dem,
                        self.parameters.get("spacing_mm", 0.75),
                        x_min_model, y_min_model, x_max_model, y_max_model
                    )

                    if self.isCanceled():
                        return False

                    if self.parameters.get("stl_format") == "ascii":
                        self.write_ascii(path, dem_model)
                    else:
                        self.write_binary(path, dem_model)

                    current_op += 1
                    self.setProgress((current_op / total_ops) * 100)

            print("[DEMto3D] STL-Datei erfolgreich geschrieben.")
            return True

        except Exception as e:
            print(f"[DEMto3D] Fehler in STLTask.run(): {e}")
            traceback.print_exc()
            return False

    def write_ascii(self, fileName, demData):
        f = open(fileName, "w")
        f.write("solid model\n")

        dem = self.face_dem_vector(demData)
        for face in dem:
            if self.isCanceled():
                f.close()
                return
            f.write("   facet normal 0 0 -1 \n")
            f.write("       outer loop\n")
            f.write("           vertex " + str(getattr(face[1], "x")) + " " + str(getattr(face[1], "y")) + " 0\n")
            f.write("           vertex " + str(getattr(face[0], "x")) + " " + str(getattr(face[0], "y")) + " 0\n")
            f.write("           vertex " + str(getattr(face[2], "x")) + " " + str(getattr(face[2], "y")) + " 0\n")
            f.write("       endloop\n")
            f.write("   endfacet\n")

        wall = self.face_wall_vector(demData)
        for face in wall:
            if self.isCanceled():
                f.close()
                return
            f.write("   facet normal " + str(getattr(face[3], "normal_x")) + " " +
                    str(getattr(face[3], "normal_y")) + " " + str(getattr(face[3], "normal_z")) + "\n")
            f.write("       outer loop\n")
            f.write("           vertex " + str(getattr(face[0], "x")) + " " + str(getattr(face[0], "y")) +
                    " " + str(getattr(face[0], "z")) + "\n")
            f.write("           vertex " + str(getattr(face[1], "x")) + " " + str(getattr(face[1], "y")) +
                    " " + str(getattr(face[1], "z")) + "\n")
            f.write("           vertex " + str(getattr(face[2], "x")) + " " + str(getattr(face[2], "y")) +
                    " " + str(getattr(face[2], "z")) + "\n")
            f.write("       endloop\n")
            f.write("   endfacet\n")

        for face in dem:
            if self.isCanceled():
                f.close()
                return
            f.write("   facet normal " + str(getattr(face[3], "normal_x")) + " " +
                    str(getattr(face[3], "normal_y")) + " " + str(getattr(face[3], "normal_z")) + "\n")
            f.write("       outer loop\n")
            f.write("           vertex " + str(getattr(face[0], "x")) + " " + str(getattr(face[0], "y")) +
                    " " + str(getattr(face[0], "z")) + "\n")
            f.write("           vertex " + str(getattr(face[1], "x")) + " " + str(getattr(face[1], "y")) +
                    " " + str(getattr(face[1], "z")) + "\n")
            f.write("           vertex " + str(getattr(face[2], "x")) + " " + str(getattr(face[2], "y")) +
                    " " + str(getattr(face[2], "z")) + "\n")
            f.write("       endloop\n")
            f.write("   endfacet\n")

        f.write("endsolid model\n")
        f.close()

    def write_binary(self, fileName, demData):
        stream = None
        try:
            counter = 0
            stream = open(fileName, "wb")
            stream.seek(0)
            stream.write(struct.pack(BINARY_HEADER, b'Python Binary STL Writer', counter))

            dem = self.face_dem_vector(demData)
            for face in dem:
                if self.isCanceled():
                    stream.close()
                    return
                counter += 1
                data = [
                    0, 0, -1,
                    getattr(face[1], "x"), getattr(face[1], "y"), 0,
                    getattr(face[0], "x"), getattr(face[0], "y"), 0,
                    getattr(face[2], "x"), getattr(face[2], "y"), 0,
                    0
                ]
                stream.write(struct.pack(BINARY_FACET, *data))

            wall = self.face_wall_vector(demData)
            for face in wall:
                if self.isCanceled():
                    stream.close()
                    return
                counter += 1
                data = [
                    getattr(face[3], "normal_x"), getattr(face[3], "normal_y"), getattr(face[3], "normal_z"),
                    getattr(face[0], "x"), getattr(face[0], "y"), getattr(face[0], "z"),
                    getattr(face[1], "x"), getattr(face[1], "y"), getattr(face[1], "z"),
                    getattr(face[2], "x"), getattr(face[2], "y"), getattr(face[2], "z"),
                    0
                ]
                stream.write(struct.pack(BINARY_FACET, *data))

            for face in dem:
                if self.isCanceled():
                    stream.close()
                    return
                counter += 1
                data = [
                    getattr(face[3], "normal_x"), getattr(face[3], "normal_y"), getattr(face[3], "normal_z"),
                    getattr(face[0], "x"), getattr(face[0], "y"), getattr(face[0], "z"),
                    getattr(face[1], "x"), getattr(face[1], "y"), getattr(face[1], "z"),
                    getattr(face[2], "x"), getattr(face[2], "y"), getattr(face[2], "z"),
                    0
                ]
                stream.write(struct.pack(BINARY_FACET, *data))

            stream.seek(0)
            stream.write(struct.pack(BINARY_HEADER, b'Python Binary STL Writer', counter))
            stream.close()
        except (IOError, OSError):
            if stream:
                stream.close()

    def face_wall_vector(self, matrix_dem):
        borders = self.parameters["borders"]
        if borders > 0:
            return self.face_wall_borders_vector(matrix_dem)
        else:
            return self.face_wall_No_borders_vector(matrix_dem)

    def face_wall_No_borders_vector(self, matrix_dem):
        rows = len(matrix_dem)
        cols = len(matrix_dem[0])
        vector_face = []
        d = 0
        for j in range(rows - 1):
            p1 = matrix_dem[j][0]._replace(z=d)
            p2 = matrix_dem[j + 1][0]
            p3 = matrix_dem[j][0]
            p4 = matrix_dem[j + 1][0]._replace(z=d)
            v_normal = self.normal(normal_x=0, normal_y=-1, normal_z=0)
            vector_face.append([p1, p2, p3, v_normal])
            vector_face.append([p1, p4, p2, v_normal])

            p1 = matrix_dem[j][cols - 1]
            p2 = matrix_dem[j + 1][cols - 1]
            p3 = matrix_dem[j][cols - 1]._replace(z=d)
            p4 = matrix_dem[j + 1][cols - 1]._replace(z=d)
            v_normal = self.normal(normal_x=0, normal_y=1, normal_z=0)
            vector_face.append([p1, p2, p3, v_normal])
            vector_face.append([p2, p4, p3, v_normal])
        for j in range(cols - 1):
            p3 = matrix_dem[0][j]._replace(z=d)
            p2 = matrix_dem[0][j + 1]
            p1 = matrix_dem[0][j]
            p4 = matrix_dem[0][j + 1]._replace(z=d)
            v_normal = self.normal(normal_x=-1, normal_y=0, normal_z=0)
            vector_face.append([p1, p2, p3, v_normal])
            vector_face.append([p2, p4, p3, v_normal])
            p1 = matrix_dem[rows - 1][j]._replace(z=d)
            p2 = matrix_dem[rows - 1][j + 1]
            p3 = matrix_dem[rows - 1][j]
            p4 = matrix_dem[rows - 1][j + 1]._replace(z=d)
            v_normal = self.normal(normal_x=0, normal_y=1, normal_z=0)
            vector_face.append([p1, p2, p3, v_normal])
            vector_face.append([p1, p4, p2, v_normal])
            
        return vector_face

    def face_wall_borders_vector(self, matrix_dem):
        borders = self.parameters["borders"]
        rows = len(matrix_dem)
        cols = len(matrix_dem[0])
        vector_face = []
        d = 0

        # UPPER RIGHT CORNER
        p0 = matrix_dem[0][cols-1]
        p0x, p0y, p0z = getattr(p0, "x"), getattr(p0, "y"), getattr(p0, "z")
        p1 = self.pto(x=p0x, y=p0y, z=p0z)
        p2 = self.pto(x=p0x+borders, y=p0y+borders, z=d)
        p3 = self.pto(x=p0x, y=p0y+borders, z=d)
        p4 = self.pto(x=p0x+borders, y=p0y, z=d)
        vector_face.append([p1, p2, p3, self.get_normal(p1, p2, p3)])
        vector_face.append([p1, p4, p2, self.get_normal(p1, p4, p2)])
        p1 = p1._replace(z=d)
        v_normal = self.normal(normal_x=0, normal_y=0, normal_z=-1)
        vector_face.append([p1, p3, p2, v_normal])
        vector_face.append([p1, p2, p4, v_normal])

        # UPPER LEFT CORNER
        p0 = matrix_dem[0][0]
        p0x, p0y, p0z = getattr(p0, "x"), getattr(p0, "y"), getattr(p0, "z")
        p1 = self.pto(x=p0x, y=p0y, z=p0z)
        p2 = self.pto(x=p0x-borders, y=p0y+borders, z=d)
        p3 = self.pto(x=p0x-borders, y=p0y, z=d)
        p4 = self.pto(x=p0x, y=p0y+borders, z=d)
        vector_face.append([p1, p2, p3, self.get_normal(p1, p2, p3)])
        vector_face.append([p1, p4, p2, self.get_normal(p1, p4, p2)])
        p1 = p1._replace(z=d)
        v_normal = self.normal(normal_x=0, normal_y=0, normal_z=-1)
        vector_face.append([p1, p3, p2, v_normal])
        vector_face.append([p1, p2, p4, v_normal])

        # BOTTOM LEFT CORNER
        p0 = matrix_dem[rows-1][0]
        p0x, p0y, p0z = getattr(p0, "x"), getattr(p0, "y"), getattr(p0, "z")
        p1 = self.pto(x=p0x, y=p0y, z=p0z)
        p2 = self.pto(x=p0x-borders, y=p0y-borders, z=d)
        p3 = self.pto(x=p0x, y=p0y-borders, z=d)
        p4 = self.pto(x=p0x-borders, y=p0y, z=d)
        vector_face.append([p1, p2, p3, self.get_normal(p1, p2, p3)])
        vector_face.append([p1, p4, p2, self.get_normal(p1, p4, p2)])
        p1 = p1._replace(z=d)
        v_normal = self.normal(normal_x=0, normal_y=0, normal_z=-1)
        vector_face.append([p1, p3, p2, v_normal])
        vector_face.append([p1, p2, p4, v_normal])

        # BOTTOM RIGHT CORNER
        p0 = matrix_dem[rows-1][cols-1]
        p0x, p0y, p0z = getattr(p0, "x"), getattr(p0, "y"), getattr(p0, "z")
        p1 = self.pto(x=p0x, y=p0y, z=p0z)
        p2 = self.pto(x=p0x+borders, y=p0y-borders, z=d)
        p3 = self.pto(x=p0x+borders, y=p0y, z=d)
        p4 = self.pto(x=p0x, y=p0y-borders, z=d)
        vector_face.append([p1, p2, p3, self.get_normal(p1, p2, p3)])
        vector_face.append([p1, p4, p2, self.get_normal(p1, p4, p2)])
        p1 = p1._replace(z=d)
        v_normal = self.normal(normal_x=0, normal_y=0, normal_z=-1)
        vector_face.append([p1, p3, p2, v_normal])
        vector_face.append([p1, p2, p4, v_normal])

        # LEFT & RIGHT BORDERS
        for j in range(rows - 1):
            p3 = matrix_dem[j][0]
            p2 = matrix_dem[j + 1][0]
            p1 = p3._replace(z=d, x=getattr(p3, 'x')-borders)
            p4 = p2._replace(z=d, x=getattr(p2, 'x')-borders)
            vector_face.append([p1, p2, p3, self.get_normal(p1, p2, p3)])
            vector_face.append([p1, p4, p2, self.get_normal(p1, p4, p2)])
            p2 = p2._replace(z=d)
            p3 = p3._replace(z=d)
            v_normal = self.normal(normal_x=0, normal_y=0, normal_z=-1)
            vector_face.append([p1, p3, p2, v_normal])
            vector_face.append([p1, p2, p4, v_normal])

            p1 = matrix_dem[j][cols - 1]
            p2 = matrix_dem[j + 1][cols - 1]
            p3 = p1._replace(z=d, x=getattr(p1, 'x')+borders)
            p4 = p2._replace(z=d, x=getattr(p2, 'x')+borders)
            vector_face.append([p1, p2, p3, self.get_normal(p1, p2, p3)])
            vector_face.append([p2, p4, p3, self.get_normal(p1, p4, p2)])
            p1 = p1._replace(z=d)
            p2 = p2._replace(z=d)
            v_normal = self.normal(normal_x=0, normal_y=0, normal_z=-1)
            vector_face.append([p1, p3, p2, v_normal])
            vector_face.append([p2, p3, p4, v_normal])

        # UPPER & BOTTOM BORDERS
        for j in range(cols - 1):
            p1 = matrix_dem[0][j]
            p2 = matrix_dem[0][j + 1]
            p3 = p1._replace(z=d, y=getattr(p1, 'y')+borders)
            p4 = p2._replace(z=d, y=getattr(p2, 'y')+borders)
            vector_face.append([p1, p2, p3, self.get_normal(p1, p2, p3)])
            vector_face.append([p2, p4, p3, self.get_normal(p2, p4, p3)])
            p1 = p1._replace(z=d)
            p2 = p2._replace(z=d)
            v_normal = self.normal(normal_x=0, normal_y=0, normal_z=-1)
            vector_face.append([p1, p3, p2, v_normal])
            vector_face.append([p2, p3, p4, v_normal])

            p2 = matrix_dem[rows - 1][j + 1]
            p3 = matrix_dem[rows - 1][j]
            p1 = p3._replace(z=d, y=getattr(p3, 'y')-borders)
            p4 = p2._replace(z=d, y=getattr(p2, 'y')-borders)
            vector_face.append([p1, p2, p3, self.get_normal(p1, p2, p3)])
            vector_face.append([p1, p4, p2, self.get_normal(p1, p4, p2)])
            p2 = p2._replace(z=d)
            p3 = p3._replace(z=d)
            v_normal = self.normal(normal_x=0, normal_y=0, normal_z=-1)
            vector_face.append([p1, p3, p2, v_normal])
            vector_face.append([p1, p2, p4, v_normal])
        return vector_face

    def face_dem_vector(self, matrix_dem):
        rows = len(matrix_dem)
        cols = len(matrix_dem[0])
        vector_face = []

        for j in range(rows - 1):
            for k in range(cols - 1):
                p3 = matrix_dem[j][k]
                p2 = matrix_dem[j][k + 1]
                p1 = matrix_dem[j + 1][k]
                p4 = matrix_dem[j + 1][k + 1]
                vector_face.append([p1, p2, p3, self.get_normal(p1, p2, p3)])
                vector_face.append([p1, p4, p2, self.get_normal(p1, p4, p2)])

        return vector_face

    def get_normal(self, p1, p2, p3):
        try:
            v = [getattr(p2, "x") - getattr(p1, "x"), getattr(p2, "y") - getattr(p1, "y"),
                 getattr(p2, "z") - getattr(p1, "z")]
            w = [getattr(p3, "x") - getattr(p1, "x"), getattr(p3, "y") - getattr(p1, "y"),
                 getattr(p3, "z") - getattr(p1, "z")]

            x = (v[1] * w[2]) - (v[2] * w[1])
            y = (v[2] * w[0]) - (v[0] * w[2])
            z = (v[0] * w[1]) - (v[1] * w[0])
            modulo = math.sqrt(x * x + y * y + z * z)

            return self.normal(normal_x=x / modulo, normal_y=y / modulo, normal_z=z / modulo)
        except ZeroDivisionError:
            return self.normal(normal_x=0, normal_y=0, normal_z=0)

    @staticmethod
    def cut_dem(matrix_dem_build, resolution, x_min, y_min, x_max, y_max):
        rows = len(matrix_dem_build)
        cols = len(matrix_dem_build[0])
        dem = []
        for i in range(rows):
            aux = []
            for j in range(cols):
                x = getattr(matrix_dem_build[i][j], "x")
                y = getattr(matrix_dem_build[i][j], "y")
                if x_min <= x <= x_max and y_min <= y <= y_max:
                    aux.append(matrix_dem_build[i][j])
                elif 0 < (x - x_max) < resolution and y_min <= y <= y_max:
                    aux.append(matrix_dem_build[i][j])
                elif -resolution < (y - y_min) < 0 and x_min <= x <= x_max:
                    aux.append(matrix_dem_build[i][j])
                elif 0 < (x - x_max) < resolution and - resolution < (y - y_min) < 0:
                    aux.append(matrix_dem_build[i][j])
            if aux:
                dem.append(aux)
        return dem