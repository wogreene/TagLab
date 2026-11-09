from PyQt5.QtCore import Qt, QTimer, QEvent
from PyQt5.QtWidgets import QLabel, QApplication


class QtToastMessage(QLabel):
    """
    A small warning shown over the top of a viewer. It goes away on its own after a few seconds, and as soon as the user
    does anything else: a click, a key, the wheel, or moving or resizing the window.
    """

    def __init__(self, viewer):
        super(QtToastMessage, self).__init__(viewer)

        self.viewer = viewer

        self.setStyleSheet("QLabel { background-color: rgb(120,85,10); color: white; border: 1px solid rgb(220,160,40);"
                           " border-radius: 6px; padding: 6px 12px; }")
        self.setAlignment(Qt.AlignCenter)
        self.setTextFormat(Qt.PlainText)
        self.setWordWrap(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)

        self.hide()

    def showText(self, text, timeout=4000):

        self.setText(text)
        self.setMaximumWidth(max(200, self.viewer.width() - 40))
        self.adjustSize()
        self.move(max(0, (self.viewer.width() - self.width()) // 2), 12)
        self.show()
        self.raise_()

        # installing it twice is harmless: Qt ignores a filter that is already installed
        QApplication.instance().installEventFilter(self)
        self.timer.start(timeout)

    def dismiss(self):

        self.timer.stop()
        self.hide()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def eventFilter(self, obj, event):

        t = event.type()

        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick, QEvent.KeyPress, QEvent.Wheel):
            self.dismiss()

        elif t in (QEvent.Move, QEvent.Resize, QEvent.WindowStateChange) and obj is self.viewer.window():
            self.dismiss()

        return False
