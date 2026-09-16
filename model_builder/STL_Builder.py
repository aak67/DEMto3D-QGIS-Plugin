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

from builtins import str
from builtins import range
import collections
import struct
import math
import traceback
from qgis.core import QgsTask

BINARY_HEADER = "80sI"
BINARY_FACET = "12fH"
BUFFER_SIZE = 4 * 1024 * 1024  # 4 MB Schreibpuffer


class STLTask(QgsTask):
    """Class where is built the stl file from the mesh point that decribe the model surface"""
    normal = collections.namedtuple('normal', 'normal_x normal_y normal_z')
    pto = collections.namedtuple('pto', 'x y z')

    def __init__(self, parameters, stl_file, dem_matrix):
        super().__init__("DEMto3D STL Export", QgsTask.CanCancel)
        self.parameters = parameters
        self.stl_file = stl_file
        self.matrix_dem = dem_matrix

    def run(self):
        print("[DEMto3D] STLTask.run() wurde von QGIS gestartet.")
        try:
            rows = len(self.matrix_dem)
            cols = len(self.matrix_dem[0]) if rows > 0 else 0
            
            if rows == 0 or cols == 0:
                return False

            # --- PHASE 1: Triangles / Vertices generieren (0 % - 50 %) ---
            triangles = []
            
            for i in range(rows - 1):
                if self.isCanceled():
                    return False

                for j in range(cols - 1):
                    # Vertices für die Quad-To-Triangle Umwandlung berechnen
                    p1 = self.matrix_dem[i][j]
                    p2 = self.matrix_dem[i][j + 1]
                    p3 = self.matrix_dem[i + 1][j]
                    p4 = self.matrix_dem[i + 1][j + 1]

                    # 2 Dreiecke pro Rasterzelle hinzufügen
                    triangles.append((p1, p3, p2))
                    triangles.append((p2, p3, p4))

                # Fortschritt für Phase 1 senden (0 bis 50%)
                progress_phase1 = (i / (rows - 1)) * 50.0
                self.setProgress(progress_phase1)

            # --- PHASE 2: Seitenränder, Boden & STL-Schreiben (50 % - 100 %) ---
            # (Beispiel für binäres Schreiben)
            total_triangles = len(triangles)
            
            with open(self.stl_file, 'wb') as f:
                # 80-Byte-Header schreiben
                f.write(b'\x00' * 80)
                # Anzahl der Dreiecke schreiben (4-Byte Unsigned Int)
                f.write(struct.pack('<I', total_triangles))

                # Dreiecke in Datei schreiben und Fortschritt weiterschalten
                for idx, tri in enumerate(triangles):
                    if self.isCanceled():
                        return False

                    # Normalenvektor + 3 Punkte schreiben
                    # (Dummy-Normalenvektor 0,0,0 reicht für 3D-Drucker meist aus)
                    f.write(struct.pack('<12fH', 
                        0.0, 0.0, 0.0,
                        tri[0].x, tri[0].y, tri[0].z,
                        tri[1].x, tri[1].y, tri[1].z,
                        tri[2].x, tri[2].y, tri[2].z,
                        0
                    ))

                    # Nur alle 5000 Dreiecke das UI aktualisieren (spart Overhead)
                    if idx % 5000 == 0:
                        progress_phase2 = 50.0 + (idx / total_triangles) * 50.0
                        self.setProgress(progress_phase2)

            self.setProgress(100.0)
            return True

        except Exception as e:
            print(f"[DEMto3D] Fehler in STLTask: {e}")
            return False

    def write_ascii(self, fileName, demData, progress_callback=None):
        dem = self.face_dem_vector(demData)
        wall = self.face_wall_vector(demData)
        
        all_faces = []
        
        # Boden (Dem-Faces umgekehrt/flach)
        for face in dem:
            all_faces.append((0, 0, -1, face[1], face[0], face[2]))
            
        # Wände
        for face in wall:
            n = face[3]
            all_faces.append((n.normal_x, n.normal_y, n.normal_z, face[0], face[1], face[2]))
            
        # Oberfläche
        for face in dem:
            n = face[3]
            all_faces.append((n.normal_x, n.normal_y, n.normal_z, face[0], face[1], face[2]))

        total_faces = len(all_faces)
        buffer = ["solid model\n"]
        chunk_size = 5000

        with open(fileName, "w", buffering=BUFFER_SIZE) as f:
            for idx, (nx, ny, nz, p1, p2, p3) in enumerate(all_faces):
                if self.isCanceled():
                    return

                z1 = getattr(p1, "z", 0)
                z2 = getattr(p2, "z", 0)
                z3 = getattr(p3, "z", 0)

                buffer.append(
                    f"   facet normal {nx} {ny} {nz}\n"
                    f"       outer loop\n"
                    f"           vertex {p1.x} {p1.y} {z1}\n"
                    f"           vertex {p2.x} {p2.y} {z2}\n"
                    f"           vertex {p3.x} {p3.y} {z3}\n"
                    f"       endloop\n"
                    f"   endfacet\n"
                )

                if len(buffer) >= chunk_size:
                    f.write("".join(buffer))
                    buffer.clear()
                    if progress_callback and total_faces > 0:
                        progress_callback((idx / total_faces) * 100.0)

            buffer.append("endsolid model\n")
            f.write("".join(buffer))

    def write_binary(self, fileName, demData, progress_callback=None):
        dem = self.face_dem_vector(demData)
        wall = self.face_wall_vector(demData)

        all_facets = []

        # Boden (Dem-Faces umgekehrt/flach)
        for face in dem:
            all_facets.append((
                0.0, 0.0, -1.0,
                face[1].x, face[1].y, 0.0,
                face[0].x, face[0].y, 0.0,
                face[2].x, face[2].y, 0.0
            ))

        # Wände
        for face in wall:
            n = face[3]
            all_facets.append((
                n.normal_x, n.normal_y, n.normal_z,
                face[0].x, face[0].y, face[0].z,
                face[1].x, face[1].y, face[1].z,
                face[2].x, face[2].y, face[2].z
            ))

        # Oberfläche
        for face in dem:
            n = face[3]
            all_facets.append((
                n.normal_x, n.normal_y, n.normal_z,
                face[0].x, face[0].y, face[0].z,
                face[1].x, face[1].y, face[1].z,
                face[2].x, face[2].y, face[2].z
            ))

        total_facets = len(all_facets)

        with open(fileName, "wb", buffering=BUFFER_SIZE) as stream:
            # Platzhalter-Header schreiben
            stream.write(struct.pack(BINARY_HEADER, b'Python Binary STL Writer', total_facets))

            facet_struct = struct.Struct(BINARY_FACET)
            chunk_size = 10000
            buffer = bytearray()

            for idx, facet_data in enumerate(all_facets):
                if self.isCanceled():
                    return

                buffer.extend(facet_struct.pack(*facet_data, 0))

                if (idx + 1) % chunk_size == 0:
                    stream.write(buffer)
                    buffer.clear()
                    if progress_callback and total_facets > 0:
                        progress_callback(((idx + 1) / total_facets) * 100.0)

            if buffer:
                stream.write(buffer)

            # Header mit exakter Facettenanzahl überschreiben
            stream.seek(0)
            stream.write(struct.pack(BINARY_HEADER, b'Python Binary STL Writer', total_facets))

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