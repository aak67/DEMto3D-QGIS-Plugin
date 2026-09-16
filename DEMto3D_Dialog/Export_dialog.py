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

from __future__ import absolute_import
import os

from qgis.PyQt.QtWidgets import QMessageBox, QDialog
from qgis.core import QgsApplication

from ..model_builder.Model_Builder import ModelTask
from ..model_builder.STL_Builder import STLTask


class Export(QDialog):

    def __init__(self, mainDialog, parameters, file_name):
        super(Export, self).__init__()
        self.mainDlg = mainDialog
        self.parameters = parameters
        self.stl_file = file_name
        self.task = None

        self.prepareUi(True)
        self.do_model()

    def do_model(self):
        print("[DEMto3D] Starte ModelTask...")
        self.mainDlg.ui.progressBar.setMaximum(100)
        self.mainDlg.ui.progressBar.setValue(0)

        self._disconnect_cancel_button()
        self.mainDlg.ui.cancelProgressToolButton.clicked.connect(self.cancel_task)
        self.mainDlg.ui.ProgressLabel.setText(self.tr("Building STL geometry"))

        try:
            self.task = ModelTask(self.parameters)
            
            self.task.progressChanged.connect(self.on_progress)
            self.task.taskCompleted.connect(self.do_stl_file)
            self.task.taskTerminated.connect(self.on_task_failed)

            task_id = QgsApplication.taskManager().addTask(self.task)
            print(f"[DEMto3D] Task gestartet mit ID: {task_id}")

        except Exception as e:
            print(f"[DEMto3D] Fehler beim Erstellen des ModelTasks: {e}")
            self.on_task_failed()

    def do_stl_file(self):
        print("[DEMto3D] ModelTask abgeschlossen. Starte STLTask...")
        self.mainDlg.ui.ProgressLabel.setText(self.tr("Exporting STL file"))

        matrix_dem = getattr(self.task, "matrix_dem", None)

        try:
            self.task = STLTask(self.parameters, self.stl_file, matrix_dem)

            self.task.progressChanged.connect(self.on_progress)
            # Hier lag der Fehler: finish_export statt on_task_finished
            self.task.taskCompleted.connect(self.finish_export)
            self.task.taskTerminated.connect(self.on_task_failed)

            task_id = QgsApplication.taskManager().addTask(self.task)
            print(f"[DEMto3D] STLTask gestartet mit ID: {task_id}")

        except Exception as e:
            print(f"[DEMto3D] Fehler beim Erstellen des STLTasks: {e}")
            self.on_task_failed()

    def on_progress(self, progress):
        self.mainDlg.ui.progressBar.setValue(int(progress))

    def cancel_task(self):
        if self.task:
            print("[DEMto3D] Task wird abgebrochen...")
            self.task.cancel()

    def finish_export(self):
        print("[DEMto3D] Export erfolgreich beendet.")
        self._disconnect_cancel_button()
        self.prepareUi(False)
        self.mainDlg.ui.progressBar.setValue(100)
        QMessageBox.information(self.mainDlg, self.mainDlg.tr("Attention"), self.mainDlg.tr("STL model generated"))

    def on_task_failed(self, *args):
        print("[DEMto3D] Task fehlgeschlagen oder abgebrochen.")
        # Hier lag der zweite Fehler: _disconnect_cancel_button statt _restore_cancel_button
        self._disconnect_cancel_button()
        self.mainDlg.ui.ProgressLabel.setText(self.tr("Export failed"))
        self.prepareUi(False)
        self.mainDlg.ui.progressBar.setValue(0)
        if os.path.exists(self.stl_file):
            try:
                os.remove(self.stl_file)
            except OSError:
                pass
        QMessageBox.information(self.mainDlg, self.mainDlg.tr("Attention"), self.mainDlg.tr("Process cancelled or failed"))

    def _disconnect_cancel_button(self):
        try:
            self.mainDlg.ui.cancelProgressToolButton.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass

    def prepareUi(self, start):
        if start:
            self.mainDlg.ui.ProgressLabel.show()
        else:
            self.mainDlg.ui.ProgressLabel.hide()
        self.mainDlg.ui.cancelProgressToolButton.setEnabled(start)
        self.mainDlg.ui.groupBox.setEnabled(not start)
        self.mainDlg.ui.groupBox_1.setEnabled(not start)
        self.mainDlg.ui.groupBox_3.setEnabled(not start)
        self.mainDlg.ui.groupBox_5.setEnabled(not start)
        self.mainDlg.ui.ParamPushButton.setEnabled(not start)
        self.mainDlg.ui.STLToolButton.setEnabled(not start)
        self.mainDlg.ui.CancelToolButton.setEnabled(not start)

    def closeEvent(self, event):
        if self.task:
            self.task.cancel()
        event.accept()