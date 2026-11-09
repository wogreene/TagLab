# One look for every scrollbar in the app: a thin dark track with a grey rounded handle and no
# arrow buttons. The native macOS scrollbar is an overlay drawn on top of the content (it hid the
# end of the last column of the tables), so the Fusion base style is used to make it take its own room.

from PyQt5.QtCore import QObject, QEvent
from PyQt5.QtWidgets import QScrollBar, QStyleFactory

SCROLLBAR_STYLESHEET = """
QScrollBar:vertical {
    width: 12px;
    margin: 0px;
    background: rgb(40,40,40);
}
QScrollBar::handle:vertical {
    min-height: 24px;
    border-radius: 4px;
    background: rgb(110,110,110);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QScrollBar:horizontal {
    height: 12px;
    margin: 0px;
    background: rgb(40,40,40);
}
QScrollBar::handle:horizontal {
    min-width: 24px;
    border-radius: 4px;
    background: rgb(110,110,110);
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}
"""


class ScrollBarStyler(QObject):
    """
    Application-wide event filter: every scrollbar is styled when it is first polished, so the
    ones created later (dialogs, panels opened on demand) match the rest.
    """

    def __init__(self, parent=None):
        super(ScrollBarStyler, self).__init__(parent)
        self.base_style = QStyleFactory.create("Fusion")

    def eventFilter(self, obj, event):

        if event.type() == QEvent.Polish and isinstance(obj, QScrollBar) and not obj.property("tagLabScrollBar"):
            obj.setProperty("tagLabScrollBar", True)
            obj.setStyle(self.base_style)
            obj.setStyleSheet(SCROLLBAR_STYLESHEET)

        return False
