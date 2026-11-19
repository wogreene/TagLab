from PyQt5.QtWidgets import QDialog, QLabel, QComboBox, QCheckBox, QDialogButtonBox, QVBoxLayout


class QtImportTimepointDialog(QDialog):
    """
    Choose the timepoint to copy the regions from, and whether the copies are linked to the originals.
    """

    def __init__(self, parent, items, default, link):
        super(QtImportTimepointDialog, self).__init__(parent)

        self.setWindowTitle("Import Regions From Another Timepoint")

        self.combo = QComboBox()
        self.combo.addItems(items)
        self.combo.setCurrentIndex(default)

        self.checkbox_link = QCheckBox("Link the copies to the originals (automatic matches)")
        self.checkbox_link.setChecked(link)
        self.checkbox_link.setToolTip(
            "Runs the same matching as Compute Automatic Matches between the two timepoints, so that each copy is "
            "matched to its original\nand belongs to the same genet. Without it the copies are plain new regions "
            "that you can match yourself later.")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Copy the regions of this timepoint onto the current one:"))
        layout.addWidget(self.combo)
        layout.addWidget(self.checkbox_link)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def selectedIndex(self):
        return self.combo.currentIndex()

    def linkRegions(self):
        return self.checkbox_link.isChecked()
