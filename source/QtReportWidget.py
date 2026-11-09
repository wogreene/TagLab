# TagLab
# A semi-automatic segmentation tool
#
# Copyright(C) 2026
# Perry Institute for Marine Science
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os

from PyQt5.QtCore import Qt, pyqtSlot, pyqtSignal
from PyQt5.QtWidgets import QWidget, QMessageBox, QSizePolicy, QLineEdit, QLabel, \
    QPushButton, QHBoxLayout, QVBoxLayout, QGridLayout, QCheckBox, QGroupBox, \
    QListWidget, QListWidgetItem, QFileDialog, QProgressBar, QApplication, \
    QDoubleSpinBox

from source import Report


class QtReportWidget(QWidget):
    """
    Chooses what goes into the statistics report and where it is written.
    """

    closed = pyqtSignal()

    def __init__(self, project, image, taglab_dir, parent=None):
        super(QtReportWidget, self).__init__(parent)

        self.project = project
        self.image = image
        self.taglab_dir = taglab_dir

        self.setStyleSheet("background-color: rgb(40,40,40); color: white")
        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding)
        self.setWindowTitle("Export statistics report")
        self.setMinimumWidth(560)

        has_dem = image is not None and image.getDEMChannel() is not None
        n_points = len(image.annotations.annpoints) if image else 0
        n_regions = len(image.annotations.seg_blobs) if image else 0

        # ------------------------------------------------ sections
        self.chk_overview = QCheckBox("Orthomosaic and DEM overview")
        self.chk_overview.setChecked(True)

        self.chk_rugosity = QCheckBox("Rugosity on a grid")
        self.chk_rugosity.setChecked(has_dem)
        self.chk_rugosity.setEnabled(has_dem)
        if not has_dem:
            self.chk_rugosity.setText("Rugosity on a grid  (needs a DEM)")

        self.chk_points = QCheckBox("Point counts  (%d points)" % n_points)
        self.chk_points.setChecked(n_points > 0)
        self.chk_points.setEnabled(n_points > 0)

        self.chk_regions = QCheckBox("Regions  (%d regions)" % n_regions)
        self.chk_regions.setChecked(n_regions > 0)
        self.chk_regions.setEnabled(n_regions > 0)

        sections = QVBoxLayout()
        for w in (self.chk_overview, self.chk_rugosity, self.chk_points, self.chk_regions):
            sections.addWidget(w)
        box_sections = QGroupBox("Include")
        box_sections.setLayout(sections)

        # ------------------------------------------------ settings
        self.spin_cell = QDoubleSpinBox()
        self.spin_cell.setRange(0.1, 50.0)
        self.spin_cell.setSingleStep(0.5)
        self.spin_cell.setDecimals(2)
        self.spin_cell.setValue(Report.DEFAULT_CELL_SIZE_M)
        self.spin_cell.setSuffix(" m")
        self.spin_cell.setEnabled(has_dem)

        has_area = bool(getattr(project, "working_area", None))
        self.chk_working_area = QCheckBox("Measure inside the working area only")
        self.chk_working_area.setChecked(has_area)
        self.chk_working_area.setEnabled(has_area)
        if not has_area:
            self.chk_working_area.setText("Measure inside the working area only  "
                                          "(none is set)")

        settings = QGridLayout()
        settings.addWidget(QLabel("Rugosity grid cell"), 0, 0)
        settings.addWidget(self.spin_cell, 0, 1)
        settings.addWidget(self.chk_working_area, 1, 0, 1, 2)
        settings.setColumnStretch(2, 1)
        box_settings = QGroupBox("Settings")
        box_settings.setLayout(settings)

        # ------------------------------------------------ the roll-up group
        self.edit_group = QLineEdit("Live coral")

        self.list_classes = QListWidget()
        self.list_classes.setMaximumHeight(150)
        self.list_classes.setStyleSheet("background-color: rgb(55,55,55);")
        for name in self.classesPresent():
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if self.looksLive(name) else Qt.Unchecked)
            self.list_classes.addItem(item)

        group = QVBoxLayout()
        group.addWidget(QLabel("Classes counted into the group, and what to call it. "
                               "Leave none ticked to omit the roll-up."))
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Group name"))
        name_row.addWidget(self.edit_group)
        group.addLayout(name_row)
        group.addWidget(self.list_classes)
        box_group = QGroupBox("Point count roll-up")
        box_group.setLayout(group)

        # ------------------------------------------------ output
        self.edit_path = QLineEdit(self.defaultPath())
        btn_browse = QPushButton("...")
        btn_browse.setMaximumWidth(40)
        btn_browse.clicked.connect(self.chooseFile)

        out = QHBoxLayout()
        out.addWidget(QLabel("Save to"))
        out.addWidget(self.edit_path)
        out.addWidget(btn_browse)

        # ------------------------------------------------ buttons
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.lbl_status = QLabel("")

        self.btn_export = QPushButton("Export")
        self.btn_export.clicked.connect(self.exportReport)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(btn_cancel)
        buttons.addWidget(self.btn_export)

        layout = QVBoxLayout()
        layout.addWidget(box_sections)
        layout.addWidget(box_settings)
        layout.addWidget(box_group)
        layout.addLayout(out)
        layout.addWidget(self.lbl_status)
        layout.addWidget(self.progress)
        layout.addLayout(buttons)
        self.setLayout(layout)

    # ---------------------------------------------------------------- helpers

    def classesPresent(self):
        """The classes actually used by the points on this map, most common first."""

        if self.image is None:
            return []

        counts = {}
        for p in self.image.annotations.annpoints:
            counts[p.class_name] = counts.get(p.class_name, 0) + 1

        return sorted(counts, key=lambda k: -counts[k])

    def looksLive(self, name):
        """
        A first guess at whether a class belongs in the roll-up.

        There is nothing in a dictionary that says which classes are live coral, so the
        obvious background names are excluded and everything else is offered as ticked.
        It is a starting point for the list, not a classification.
        """

        lowered = name.strip().lower()
        background = ("empty", "unknown", "background", "not coral", "notc", "nonc",
                      "substrate", "sand", "rubble", "water", "other", "unclassified")

        return lowered not in background

    def defaultPath(self):
        name = self.image.name if self.image else "report"
        safe = "".join(c for c in name if c.isalnum() or c in ("-", "_", " ")).strip()
        safe = safe.replace(" ", "_") or "report"
        base = self.taglab_dir or os.getcwd()

        return os.path.join(base, safe + "_statistics.pdf")

    def selectedSections(self):
        chosen = []
        if self.chk_overview.isChecked():
            chosen.append("overview")
        if self.chk_rugosity.isChecked():
            chosen.append("rugosity")
        if self.chk_points.isChecked():
            chosen.append("points")
        if self.chk_regions.isChecked():
            chosen.append("regions")

        return chosen

    def selectedClasses(self):
        chosen = []
        for i in range(self.list_classes.count()):
            item = self.list_classes.item(i)
            if item.checkState() == Qt.Checked:
                chosen.append(item.text())

        return chosen

    # ---------------------------------------------------------------- slots

    @pyqtSlot()
    def chooseFile(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Save the report",
                                                  self.edit_path.text(), "PDF (*.pdf)")
        if filename:
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"
            self.edit_path.setText(filename)

    def report(self, text, fraction):
        self.lbl_status.setText(text)
        self.progress.setValue(int(100 * fraction))
        QApplication.processEvents()

    @pyqtSlot()
    def exportReport(self):
        sections = self.selectedSections()
        if not sections:
            QMessageBox.information(self, "Export statistics report",
                                    "Nothing is ticked, so there would be nothing in the "
                                    "report. Choose at least one section.")
            return

        filename = self.edit_path.text().strip()
        if not filename:
            QMessageBox.information(self, "Export statistics report",
                                    "Choose where to save the report.")
            return

        self.progress.setVisible(True)
        self.btn_export.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            written = Report.writeReport(
                filename, self.project, self.image,
                sections=sections,
                cell_size_m=self.spin_cell.value(),
                group_classes=self.selectedClasses(),
                group_label=self.edit_group.text().strip() or "Selected classes",
                use_working_area=self.chk_working_area.isChecked(),
                progress=self.report)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.progress.setVisible(False)
            self.btn_export.setEnabled(True)
            QMessageBox.warning(self, "Export statistics report",
                                "The report could not be written.\n\n%s" % str(e))
            return

        QApplication.restoreOverrideCursor()
        self.progress.setVisible(False)
        self.btn_export.setEnabled(True)

        if not written:
            QMessageBox.information(
                self, "Export statistics report",
                "There was nothing to report on this map, so no file was written.\n\n"
                "Every section asked for came back empty. If rugosity was one of them, "
                "a grid cell larger than the surveyed area leaves no cell complete "
                "enough to measure - try a smaller one.")
            return

        skipped = [s for s in sections if s not in written]
        message = "Wrote %d page%s to\n%s" % (len(written),
                                              "" if len(written) == 1 else "s", filename)
        if skipped:
            message += ("\n\nLeft out, having nothing to report on this map: %s"
                        % ", ".join(skipped))
        QMessageBox.information(self, "Export statistics report", message)
        self.close()

    def closeEvent(self, event):
        self.closed.emit()
        super(QtReportWidget, self).closeEvent(event)
