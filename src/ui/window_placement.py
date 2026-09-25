"""保留 Windows 原生分屏行为，并记住窗口位置与大小。"""

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer
from PySide6.QtGui import QCursor, QGuiApplication


def right_panel_rect(area: QRect) -> QRect:
    """右侧约三分之一，使用 Qt 逻辑坐标适配显示缩放和多屏。"""
    width = min(area.width(), max(340, min(600, round(area.width() / 3))))
    return QRect(area.right() - width + 1, area.top(), width, area.height())


class WindowPlacement(QObject):
    def __init__(self, window, settings):
        super().__init__(window)
        self.window = window
        self.settings = settings
        self.restored = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.save)
        window.installEventFilter(self)

    def _screen(self):
        return (QGuiApplication.screenAt(QCursor.pos())
                or QGuiApplication.primaryScreen())

    def restore(self):
        if self.restored:
            return
        self.restored = True
        point = QPoint(self.settings.window_x, self.settings.window_y) if (
            self.settings.window_x is not None and self.settings.window_y is not None
        ) else None
        screen = (QGuiApplication.screenAt(point) if point is not None else None) or self._screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        width = min(self.settings.window_width, area.width())
        height = min(self.settings.window_height, max(360, area.height() - 40))
        self.window.resize(width, height)
        if point is None:
            point = QPoint(area.x() + max(0, (area.width() - width) // 2),
                           area.y() + max(0, (area.height() - height) // 3))
        point.setX(max(area.left(), min(point.x(), area.right() - width + 1)))
        point.setY(max(area.top(), min(point.y(), area.bottom() - height - 32)))
        self.window.move(point)

    def place_right(self):
        screen = self.window.screen() or self._screen()
        if screen is None:
            return
        self.window.showNormal()
        self.restored = True
        rect = right_panel_rect(screen.availableGeometry())
        frame = self.window.frameGeometry()
        extra_width = max(0, frame.width() - self.window.width())
        extra_height = max(0, frame.height() - self.window.height())
        content_width = max(self.window.minimumWidth(), rect.width() - extra_width)
        self.window.resize(content_width, rect.height() - extra_height)
        self.window.move(rect.right() - content_width - extra_width + 1, rect.top())
        self.save()

    def save(self):
        if not self.restored or self.window.isMinimized():
            return
        maximized = self.window.isMaximized()
        old = self.settings.to_dict()
        self.settings.window_maximized = maximized
        if not maximized:
            self.settings.window_width = self.window.width()
            self.settings.window_height = self.window.height()
            self.settings.window_x = self.window.pos().x()
            self.settings.window_y = self.window.pos().y()
        if self.settings.to_dict() != old:
            try:
                self.settings.save()
            except OSError:
                pass

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Move, QEvent.Resize, QEvent.WindowStateChange):
            if self.restored and self.window.isVisible():
                self.timer.start()
        return super().eventFilter(obj, event)
