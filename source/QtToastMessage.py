from PyQt5.QtCore import Qt, QTimer, QEvent, QObject
from PyQt5.QtWidgets import QLabel, QApplication


class ToastDismisser(QObject):
    """
    The single application-wide event filter that takes the warnings down when the user does something else. It is
    created once and owned by the application, and the warnings only register with it while they are on screen.
    (A filter installed and removed by each warning, and living in the warning, could be called after the warning was
    destroyed, which crashed the program when it was closed with a warning still up.)
    """

    instance = None

    @classmethod
    def get(cls):
        if cls.instance is None:
            app = QApplication.instance()
            cls.instance = cls(app)
            app.installEventFilter(cls.instance)
        return cls.instance

    def __init__(self, parent):
        super(ToastDismisser, self).__init__(parent)
        self.toasts = []

    def add(self, toast):
        if toast not in self.toasts:
            self.toasts.append(toast)

    def remove(self, toast):
        if toast in self.toasts:
            self.toasts.remove(toast)

    def eventFilter(self, obj, event):

        if not self.toasts:
            return False

        t = event.type()

        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick, QEvent.KeyPress, QEvent.Wheel):
            for toast in list(self.toasts):
                try:
                    toast.dismiss()
                except RuntimeError:
                    # the warning has been destroyed: nothing left to take down
                    self.remove(toast)

        elif t in (QEvent.Move, QEvent.Resize, QEvent.WindowStateChange):
            for toast in list(self.toasts):
                try:
                    if obj is toast.viewer.window():
                        toast.dismiss()
                except RuntimeError:
                    # the viewer is already gone
                    self.remove(toast)

        return False


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

        ToastDismisser.get().add(self)
        self.timer.start(timeout)

    def dismiss(self):

        self.timer.stop()
        self.hide()
        if ToastDismisser.instance is not None:
            ToastDismisser.instance.remove(self)
