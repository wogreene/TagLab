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

    Each scrollbar gets a style object of its own, owned by the scrollbar. A widget does not own its style, so a
    style shared by all of them (and owned by this filter, hence by the application) was destroyed with the
    application before the scrollbars that used it, which crashed the program when it was closed.
    """

    def eventFilter(self, obj, event):

        if event.type() == QEvent.Polish and isinstance(obj, QScrollBar) and not obj.property("tagLabScrollBar"):
            obj.setProperty("tagLabScrollBar", True)
            style = QStyleFactory.create("Fusion")
            style.setParent(obj)
            obj.setStyle(style)
            obj.setStyleSheet(SCROLLBAR_STYLESHEET)

        return False
